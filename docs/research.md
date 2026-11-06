# Research and integration sources

Inspected on 2026-11-06:

- [SPIN workshop and challenge](https://spin-workshop.github.io/): November 12,
  2026 event; published registration deadline October 12; final task rules still
  pending on the public page. Confirm eligibility and scoring with organizers.
- [Dream-1 research](https://dreamlabs.ai/research/dream-1/): bimanual model with
  overhead and wrist observations; native joints versus EEF transfer. Reported
  demonstrations are evidence of capability, not guarantees for this cell/task.
- [Official Dream client](https://github.com/dreamlabs-co/dreamlabs/tree/main/dream_library/dream_client)
  and installed `dreamlabs-client` source: public SDK lifecycle, observation keys,
  gripper convention, timing, reset, session errors, action chunks and IK dependency.
- [Dream platform documentation](https://platform.dreamlabs.ai/api-documentation):
  authenticated account-specific setup remains authoritative for your checkpoint.
- [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) and
  [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
  multimodal Responses adapter and typed planner decisions.
- [Inspect Robots](https://github.com/robocurve/inspect-robots) and
  [YAM adapter](https://github.com/robocurve/inspect-robots-yam): policy/embodiment/task
  separation, repeatable evaluation, logs, and camera freshness. Spill uses these
  architectural ideas while preserving Karma as its only motor backend.

Local source inspection covered Karma's arm/session interfaces, native lifecycle,
`power_up`/`power_down`, camera capture, Viser predicted chunks, gripper convention,
URDF joint chain, state guards and native heartbeat protections. No external robot
driver was copied into Spill. Dependency versions are recorded in `uv.lock`.

Performance must be measured on the real rig. Start with a Dream-only baseline
and compare the hierarchical harness on the same scenes. Report completion,
spills/residue, interventions, elapsed time, API usage, provider RTT and rejected
chunks. A more elaborate planner is useful only if it improves those results.

The installed Dream dataset validator additionally established training-rate
constraints: 30/15/10/5 Hz, and a minimum 1.6-second episode span. Spill explicitly
downsamples 20 Hz command records to 10 Hz. A synthetic exported dataset was
checked with the official validator; this is format validation, not robot evidence.
