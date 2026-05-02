# Update Summary

Release ID: `2026.05.02-040`

## Highlights

- DCA trading bots now execute the first scheduled buy immediately after a
  newly enabled bot is created.
- Trading bot cards now show the next execution time and a live countdown, so
  users can tell whether a bot is ready, cooling down, disabled, or exhausted.
- Trading bot actions now return visible pending, success, and failure messages
  instead of silently doing nothing when a backend operation fails.
- Workflow strategy tooling now includes reusable base templates plus a more
  complete node graph editor with visible edges and inline node parameter
  editing.
- The root GitHub update center now reads and displays this update summary when
  previewing or applying an update, so operators can see the release notes in
  the frontend after using the update button.

## Operator Notes

- Every future push to a shared branch must bump `APP_RELEASE_ID` and update
  this file before pushing.
- Server updates applied from the root settings page are still marked
  unverified until the operator reruns smoke, permission, and relevant trading
  tests after restart.
