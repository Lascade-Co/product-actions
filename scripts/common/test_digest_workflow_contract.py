"""Workflow lint for the delivery guarantees that execute on GitHub runners."""
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.reusable = workflow("_digest.yml")
        self.email = self.reusable["jobs"]["email"]

    def test_lock_covers_build_hold_dedupe_and_final_send_across_events(self):
        group = self.email["concurrency"]["group"]
        self.assertEqual(group, "digest-${{ inputs.workflow }}-${{ matrix.digest }}-${{ inputs.edition }}")
        self.assertEqual(self.email["concurrency"]["cancel-in-progress"], "false")
        self.assertGreaterEqual(int(self.email["timeout-minutes"]), 75)
        steps = self.email["steps"]
        build = next(i for i, step in enumerate(steps) if step.get("name") == "Build email")
        hold = next(i for i, step in enumerate(steps) if "hold.py" in step.get("run", ""))
        dedupe = next(i for i, step in enumerate(steps) if step.get("id") == "dedupe")
        self.assertLess(build, hold)
        self.assertEqual(hold + 1, dedupe)
        self.assertEqual(steps[hold]["if"], "${{ github.event_name == 'schedule' }}")
        self.assertEqual(steps[-1]["uses"], "Lascade-Co/actions/actions/seal-upload@seal-v1")
        send = steps[-2]
        self.assertIn("delivery.py", send["run"])
        send_env = send["env"]
        self.assertIn("RESEND_API_KEY", send_env)
        self.assertIn("MAIL_FROM", send_env)
        self.assertNotIn("GMAIL_USER", send_env)
        self.assertNotIn("GMAIL_APP_PASSWORD", send_env)
        self.assertEqual(send["name"], "${{ steps.settings.outputs.send_step }}")
        self.assertEqual(send["if"], "${{ !inputs.dry_run }}")

    def test_partial_matrix_dry_and_test_cannot_emit_aggregate_delivery_marker(self):
        done = self.reusable["jobs"]["done"]
        self.assertEqual(done["needs"], "email")
        self.assertEqual(done["if"], "${{ !inputs.dry_run && inputs.to == '' && needs.email.result == 'success' }}")
        self.assertEqual(self.email["strategy"]["fail-fast"], "false")
        self.assertNotIn("continue-on-error", self.email)
        for step in self.email["steps"]:
            self.assertNotIn("continue-on-error", step)

    def test_aggregate_delivery_marker_uses_the_callers_frozen_report_day(self):
        done = self.reusable["jobs"]["done"]
        self.assertEqual(done["steps"][1]["name"],
                         "Delivered ${{ inputs.edition == 'pt' && 'PT' || 'IST' }} for ${{ inputs.report_date }}")
        self.assertNotIn("report_date", self.email.get("outputs", {}))
        self.assertEqual(self.reusable["env"]["REPORT_DATE"], "${{ inputs.report_date }}")

    def test_callers_dispatch_same_branch_and_manual_both_fans_out(self):
        for name, pt, ist in [("revenue",45,11), ("reviews",47,13), ("survey",49,15), ("conversion",51,17)]:
            with self.subTest(name=name):
                caller = workflow(f"daily-{name}.yml")
                self.assertEqual([s["cron"] for s in caller["on"]["schedule"]],
                                 [f"{pt} 3,6,9 * * *", f"{ist} 13,16,19 * * *"])
                job = caller["jobs"]["email"]
                self.assertEqual(job["uses"], "./.github/workflows/_digest.yml")
                self.assertEqual(job["strategy"]["matrix"],
                                 {"include": "${{ fromJSON(needs.gate2.outputs.editions) }}"})
                self.assertEqual(job["with"]["edition"], "${{ matrix.edition }}")
                self.assertEqual(job["with"]["report_date"], "${{ matrix.report_date }}")
                self.assertEqual(caller["jobs"]["gate"]["outputs"]["editions"],
                                 "${{ steps.settings.outputs.editions }}")
                self.assertEqual(caller["jobs"]["gate2"]["outputs"]["editions"],
                                 "${{ needs.gate.outputs.editions }}")
                self.assertEqual(job["secrets"], "inherit")
                self.assertEqual(set(caller["jobs"]), {"gate", "gate2", "email"})
        checkout = next(s for s in self.email["steps"] if s.get("uses", "").startswith("actions/checkout@v7"))
        self.assertEqual(checkout["with"]["ref"], "${{ github.sha }}")

    def test_settings_can_query_the_current_runs_creation_time(self):
        self.assertEqual(self.reusable["env"].get("GH_TOKEN"), "${{ github.token }}")
        for name in ["revenue", "reviews", "survey", "conversion"]:
            with self.subTest(name=name):
                caller = workflow(f"daily-{name}.yml")
                settings = next(step for step in caller["jobs"]["gate"]["steps"]
                                if step.get("id") == "settings")
                self.assertEqual(settings.get("env", {}).get("GH_TOKEN"), "${{ github.token }}")

    def test_timing_gates_use_the_report_day_frozen_before_sleep(self):
        for name in ["revenue", "reviews", "survey", "conversion"]:
            with self.subTest(name=name):
                jobs = workflow(f"daily-{name}.yml")["jobs"]
                self.assertEqual(jobs["gate"]["outputs"]["report_date"],
                                 "${{ steps.settings.outputs.report_date }}")
                first = next(step for step in jobs["gate"]["steps"] if step.get("id") == "timing")
                self.assertEqual(first["env"].get("REPORT_DATE"), "${{ steps.settings.outputs.report_date }}")
                self.assertIn('--report-date "$REPORT_DATE"', first["run"])
                second = next(step for step in jobs["gate2"]["steps"] if step.get("id") == "timing")
                self.assertEqual(second["env"]["REPORT_DATE"], "${{ needs.gate.outputs.report_date }}")
                self.assertIn('--report-date "$REPORT_DATE"', second["run"])

    def test_digest_preview_is_sealed_pack(self):
        text = (ROOT / ".github/workflows/_digest.yml").read_text()
        self.assertNotIn("openssl", text)
        self.assertNotIn("PREVIEW_KEY", text)
        steps = self.email["steps"]
        uploads = [i for i, s in enumerate(steps) if s.get("uses", "").startswith("actions/upload-artifact@")
                   and "seal/out" not in s["with"]["path"]]
        self.assertEqual(len(uploads), 1)
        upload = steps[uploads[0]]
        self.assertEqual(upload["if"], "${{ inputs.dry_run }}")
        self.assertEqual(upload["with"]["path"],
                         "${{ runner.temp }}/seal/art/preview-${{ matrix.digest }}-${{ inputs.edition }}/")
        self.assertEqual(upload["with"]["name"], "preview-${{ matrix.digest }}-${{ inputs.edition }}")
        self.assertLessEqual(int(upload["with"]["retention-days"]), 7)
        pack = steps[uploads[0] - 1]
        self.assertEqual(pack["if"], "${{ inputs.dry_run }}")
        self.assertIn("seal-pack preview-${{ matrix.digest }}-${{ inputs.edition }} out", pack["run"])

    def test_every_job_is_sealed_first_and_last_with_the_sealed_shell(self):
        names = ["_digest.yml", "daily-incomplete-checkout.yml", "live-translation-check.yml",
                 "ta-digest-trigger.yml"] + [f"daily-{n}.yml" for n in
                 ("revenue", "reviews", "survey", "conversion", "container-credits")]
        for name in names:
            document = workflow(name)
            self.assertEqual(document["defaults"]["run"]["shell"], "seal-bash-e {0}")
            for job_id, job in document["jobs"].items():
                if "steps" not in job:
                    continue
                with self.subTest(workflow=name, job=job_id):
                    self.assertEqual(job["steps"][0]["uses"], "Lascade-Co/actions/actions/seal@seal-v1")
                    self.assertEqual(job["steps"][-1]["uses"], "Lascade-Co/actions/actions/seal-upload@seal-v1")
                    self.assertEqual(job["steps"][-1]["if"], "always()")

    def test_digest_job_has_production_environment(self):
        self.assertEqual(self.email["environment"], "production")
        for name in ("daily-revenue.yml", "daily-reviews.yml", "daily-survey.yml", "daily-conversion.yml",
                     "daily-container-credits.yml"):
            with self.subTest(name=name):
                self.assertNotIn("environment", workflow(name)["jobs"]["email"])
                self.assertEqual(workflow(name)["jobs"]["email"]["secrets"], "inherit")

    def test_recipient_input_is_not_exposed_in_actions_environment_headers(self):
        for name in ["_digest.yml", "daily-revenue.yml", "daily-reviews.yml", "daily-survey.yml", "daily-conversion.yml"]:
            document = workflow(name)
            envs = [document.get("env", {})]
            for job in document["jobs"].values():
                envs.append(job.get("env", {}))
                envs.extend(step.get("env", {}) for step in job.get("steps", []))
            for env in envs:
                self.assertNotIn("${{ inputs.to }}", env.values())


if __name__ == "__main__":
    unittest.main()
