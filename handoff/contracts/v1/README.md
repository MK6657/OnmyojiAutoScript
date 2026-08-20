# Automation Evidence Contracts v1

This directory is the neutral, read-only contract between OAS, coordinate-calibrator,
and future evidence tools. Neither project imports the other project's runtime code.

The contract defines five envelopes:

- `DeviceIdentity`: an evidence-backed device identity. ADB serial aliases alone are not
  treated as a stable identity.
- `FrameEnvelope`: immutable RGB frame metadata, mapping revision, and SHA-256.
- `CandidateEnvelope`: a reviewable coordinate or OCR candidate. It is always
  `candidate_only` and cannot authorize an OAS write.
- `EvidenceManifest`: hashes, observations, test runs, and claim status for one audit or
  live verification session.
- `BattlePreparationResult`: structured preset, soul, auto-mode, and green-mark results.

`contracts.schema.json` is JSON Schema Draft 2020-12. `examples.json` contains one valid
example for each definition. Public artifacts use `artifact://` references rather than
host absolute paths. Raw HWND values remain local evidence and are serialized as strings
to avoid cross-language integer truncation.

Compatibility rules:

- Additive optional fields are allowed within v1.
- Removing or retyping a field requires v2.
- Producers must preserve unknown fields when relaying an envelope.
- Consumers must reject a frame/candidate relationship when device identity, frame hash,
  canvas profile, or mapping revision conflicts.
- Coordinate Calibrator's `oas_candidate` export includes a `candidate_envelope`
  with these provenance fields when a trusted persisted source frame is available;
  the legacy `oas.res.v1` fields remain for compatibility.
- This contract does not add an OAS apply endpoint. Applying candidates requires a
  separate version with preview, backup, lock, hash verification, and human confirmation.
