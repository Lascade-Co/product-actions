"""Port of workflow.test.js: structural assertions on .github/workflows/chat-summary.yml.

A small evaluator handles the `${{ }}` boolean expressions the JS test ran with
`with()`; the encrypted-preview test becomes a sealed-preview test that runs the
pack step's shell with a stub seal-pack.
"""
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / ".github/workflows/chat-summary.yml").read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(SOURCE)
ON = WORKFLOW.get("on", WORKFLOW.get(True))
JOBS = WORKFLOW["jobs"]
EMAIL = JOBS["email"]
STEPS = EMAIL["steps"]
SEAL = "Lascade-Co/actions/actions/seal@seal-v1"
SEAL_UPLOAD = "Lascade-Co/actions/actions/seal-upload@seal-v1"


def namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: namespace(v) for k, v in value.items()})
    return value


def evaluate(source, context):
    expression = re.sub(r"^\$\{\{\s*|\s*\}\}$", "", source.strip())
    expression = re.sub(r"!(?!=)", " not ", expression).replace("&&", " and ").replace("||", " or ")
    return eval(expression, {"__builtins__": {}}, {k: namespace(v) for k, v in context.items()})  # noqa: S307


def interpolate(source, context):
    return re.sub(r"\$\{\{([\s\S]*?)\}\}", lambda m: str(evaluate(m.group(1), context)), source)


def context(**overrides):
    ctx = {
        "inputs": {"dry_run": False, "test_email_to": "", "product": "all", "recovery": False, "edition": ""},
        "matrix": {"product": "travel-animator", "edition": "pt", "report_date": "2026-11-01"},
        "needs": {"email": {"result": "success"}, "gate2": {"outputs": {"mode": "real"}}},
        "github": {"event_name": "schedule", "event": {"schedule": "9 13,16,19 * * *"}},
        "steps": {"settings": {"outputs": {"mode": "real", "send_step": "Deliver travel-animator PT for 2026-11-01"}},
                  "dedupe": {"outputs": {"sent": "false"}}},
    }
    ctx.update(overrides)
    return ctx


def step(step_id):
    return next(s for s in STEPS if s.get("id") == step_id)


def test_triggers_keep_the_ist_cron_and_dispatch_inputs_without_a_pt_cron():
    assert ON["schedule"] == [{"cron": "9 13,16,19 * * *"}]
    assert set(ON["workflow_dispatch"]["inputs"]) == {"product", "edition", "dry_run", "tab", "report_date",
                                                      "test_email_to", "recovery"}
    assert ON["workflow_dispatch"]["inputs"]["product"]["options"] == ["all", "travel-animator", "marine-radar"]
    assert set(ON) == {"schedule", "workflow_dispatch"}


def test_jobs_are_gate_gate2_email_done():
    # The schedule is kept alive by keepalive.yml (scripts/common/test_keepalive_workflow.py).
    assert list(JOBS) == ["gate", "gate2", "email", "done"]


def test_every_job_is_sealed_first_and_last():
    for name, job in JOBS.items():
        assert job["steps"][0] == {"name": "Seal job output", "uses": SEAL}, name
        assert job["steps"][-1] == {"if": "always()", "uses": SEAL_UPLOAD}, name
    assert WORKFLOW["defaults"]["run"]["shell"] in ("seal-bash {0}", "seal-bash-e {0}")
    assert "shell: bash" not in SOURCE


def test_secrets_are_the_claude_era_set_and_only_in_the_production_email_job():
    assert set(re.findall(r"secrets\.([A-Z_]+)", SOURCE)) == {
        "CLAUDE_API_KEY", "GOOGLE_SERVICE_ACCOUNT_JSON", "MAIL_FROM", "MAIL_TO", "MAIL_TO_PT",
        "TRAVEL_ANIMATOR_SHEET_ID", "MARINE_RADAR_SHEET_ID", "RESEND_API_KEY"}
    assert not re.search(r"GEMINI|PREVIEW_KEY|openssl|\bnode\b|\bnpm\b|catchup_gate|scripts/gate/", SOURCE)
    for name, job in JOBS.items():
        uses_secrets = "secrets." in yaml.safe_dump(job)
        assert uses_secrets == (name == "email"), name
        assert job.get("environment") == ("production" if uses_secrets else None), name
        assert "contents: read" in yaml.safe_dump(job.get("permissions", WORKFLOW["permissions"])), name


def test_private_values_stay_out_of_workflow_and_job_env():
    assert "test_email_to" not in yaml.safe_dump(WORKFLOW.get("env", {}))
    for job in JOBS.values():
        assert "test_email_to" not in yaml.safe_dump(job.get("env", {}))
    carriers = [s for s in STEPS if "inputs.test_email_to" in yaml.safe_dump(s.get("env", {}))]
    assert [s["id"] for s in carriers] == ["build"]
    assert STEPS.index(step("settings")) < STEPS.index(step("build")), "mask before any env carries the recipient"


def test_scheduled_and_recovery_sends_share_a_product_edition_lock_after_build_and_hold():
    assert EMAIL["timeout-minutes"] >= 75
    assert EMAIL["concurrency"]["cancel-in-progress"] is False
    group = EMAIL["concurrency"]["group"]
    scheduled = interpolate(group, context())
    recovery = interpolate(group, context(github={"event_name": "workflow_dispatch", "event": {}}))
    assert scheduled == recovery
    assert scheduled != interpolate(group, context(matrix={"product": "marine-radar", "edition": "pt"}))
    assert scheduled != interpolate(group, context(matrix={"product": "travel-animator", "edition": "ist"}))
    ids = [s.get("id") for s in STEPS]
    assert ids.index("settings") < ids.index("build") < ids.index("hold") < ids.index("dedupe")
    assert ids.index("dedupe") + 1 == ids.index("send"), "the history check must be immediately before sending"
    deduped = context()
    deduped["steps"]["dedupe"]["outputs"]["sent"] = "true"
    assert evaluate(step("send")["if"], deduped) is False
    assert evaluate(step("send")["if"], context()) is True
    assert step("send")["name"] == "${{ steps.settings.outputs.send_step }}"


def test_workflow_lock_resolves_the_edition_before_settings():
    group = WORKFLOW["concurrency"]["group"]
    assert interpolate(group, context()) == "digest-chat-summary-ist-schedule"
    dispatch = context(github={"event_name": "workflow_dispatch", "event": {}})
    dispatch["inputs"]["edition"] = "pt"
    assert interpolate(group, dispatch) == "digest-chat-summary-pt-workflow_dispatch"
    dispatch["inputs"]["edition"] = ""
    assert interpolate(group, dispatch) == "digest-chat-summary-both-workflow_dispatch"
    assert WORKFLOW["concurrency"]["cancel-in-progress"] is False


def test_a_partial_matrix_dry_run_test_send_or_selected_product_cannot_emit_delivered():
    done = JOBS["done"]
    assert evaluate(done["if"], context()) is True
    for result in ("failure", "cancelled", "skipped"):
        ctx = context()
        ctx["needs"]["email"]["result"] = result
        assert evaluate(done["if"], ctx) is False, result
    for change in ({"dry_run": True}, {"test_email_to": "test@example.invalid"}, {"product": "marine-radar"}):
        ctx = context()
        ctx["inputs"].update(change)
        assert evaluate(done["if"], ctx) is False, change
    ctx = context()
    ctx["inputs"]["product"] = ""
    assert evaluate(done["if"], ctx) is True
    ctx = context()
    ctx["needs"]["gate2"]["outputs"]["mode"] = "test"
    assert evaluate(done["if"], ctx) is False
    marker = next(s for s in done["steps"] if "Delivered" in s.get("name", ""))
    assert marker["name"] == "${{ format('Delivered {0} for {1}', matrix.label, matrix.report_date) }}"
    assert done["strategy"]["matrix"] == "${{ fromJSON(needs.gate2.outputs.edition_matrix) }}"


def test_preview_mode_skips_resend_and_send_is_the_last_delivery_step():
    send_index = STEPS.index(step("send"))
    dry = context()
    dry["inputs"]["dry_run"] = True
    assert evaluate(step("send")["if"], dry) is False
    for later in STEPS[send_index + 1:-1]:
        assert later.get("if"), later
        assert evaluate(later["if"], context()) is False, later.get("name")
        assert evaluate(later["if"], dry) is True, later.get("name")
    assert STEPS[-1]["uses"] == SEAL_UPLOAD


def test_build_step_runs_python_with_claude_and_names_dry_runs_like_the_send_step():
    build = step("build")
    assert build["name"] == "${{ inputs.dry_run && steps.settings.outputs.send_step || 'Build the email' }}"
    assert build["run"].strip() == 'python3 scripts/chat_summary/cs_main.py "$PRODUCT" build'
    assert build["env"]["CLAUDE_API_KEY"] == "${{ secrets.CLAUDE_API_KEY }}"
    assert build["env"]["TAB_DEADLINE"] == "${{ steps.settings.outputs.tab_deadline }}"
    assert build["env"]["TAB_NAME"] == "${{ inputs.tab }}"
    assert "RESEND_API_KEY" not in build["env"]
    assert step("send")["run"].strip() == 'python3 scripts/chat_summary/cs_main.py "$PRODUCT" send'
    assert set(step("send")["env"]) == {"RESEND_API_KEY"}
    assert any(s.get("uses") == "./.github/actions/fetch-ai" for s in STEPS[:STEPS.index(build)])


def test_hold_uses_the_shared_hold_only_on_schedule():
    hold = step("hold")
    assert hold["if"] == "${{ github.event_name == 'schedule' }}"
    assert "scripts/common/hold.py" in hold["run"] and "--target 05:55" in hold["run"]
    assert '--report-date "$REPORT_DATE"' in hold["run"]


def test_gates_use_the_shared_gate_with_the_aggregate_marker():
    for job, phase in (("gate", "1"), ("gate2", "2")):
        gate = next(s for s in JOBS[job]["steps"] if s.get("id") == "gate")
        assert f"python3 scripts/common/gate.py --phase {phase}" in gate["run"]
        for flag in ('--event "$EVENT"', "--workflow chat-summary.yml", '--sent-step "$SENT_STEP"', '--tz "$ZONE"',
                     "--target 05:05", '--report-date "$REPORT_DATE"'):
            assert flag in gate["run"], (job, flag)
        assert gate["env"]["GH_TOKEN"] == "${{ github.token }}"
    settings = next(s for s in JOBS["gate"]["steps"] if s.get("id") == "settings")
    assert settings["env"]["GH_TOKEN"] == "${{ github.token }}", "guard_real_run reads the run's creation time"
    assert "cs_editions.py settings" in settings["run"]
    assert step("settings")["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert step("dedupe")["run"].strip() == "python3 scripts/chat_summary/cs_editions.py dedupe"


def test_checkouts_are_pinned_to_the_run_sha():
    for name, job in JOBS.items():
        for s in job["steps"]:
            if str(s.get("uses", "")).startswith("actions/checkout@"):
                assert s["uses"] == "actions/checkout@v7", name
                assert s["with"]["ref"] == "${{ github.sha }}", name
    sparse = next(s for s in STEPS if str(s.get("uses", "")).startswith("actions/checkout@"))["with"]["sparse-checkout"]
    for path in ("scripts/common", "scripts/chat_summary", "scripts/fetch-ai.sh", ".github/actions/fetch-ai",
                 "requirements.txt"):
        assert path in sparse, path
    assert "PYTHONPATH" in WORKFLOW["env"]
    assert WORKFLOW["env"]["PYTHONPATH"] == "scripts/common:scripts/ai:scripts/chat_summary"


def test_sealed_preview_contains_only_the_selected_html_and_subject(tmp_path):
    pack = next(s for s in STEPS if "seal-pack" in str(s.get("run", "")))
    upload = next(s for s in STEPS if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert pack["if"] == upload["if"] == "${{ inputs.dry_run }}"
    assert upload["uses"] == "actions/upload-artifact@v7"
    assert interpolate(upload["with"]["name"], context()) == "preview-travel-animator-pt"
    assert upload["with"]["path"] == "${{ runner.temp }}/seal/art/preview-${{ matrix.product }}-${{ matrix.edition }}/"
    assert int(upload["with"]["retention-days"]) <= 7
    assert upload["with"]["if-no-files-found"] == "error"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "seal-pack").write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS_FILE"\n')
    (bin_dir / "seal-pack").chmod(0o755)
    args_file = tmp_path / "args.txt"
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "PRODUCT": "travel-animator", "EDITION": "pt",
           "ARGS_FILE": str(args_file)}
    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", pack["run"]], cwd=tmp_path, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert args_file.read_text().split("\n")[:-1] == [
        "preview-travel-animator-pt", "out/travel-animator-pt.html", "out/travel-animator-pt.subject.txt"]
