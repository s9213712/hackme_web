# Share/Profile Fixes And High-Pressure QA

Date: 2026-05-16
Runtime: `https://127.0.0.1:5010`

## Findings

No new blocking regression was confirmed in the newly fixed areas.

## Fix Verification

- Personal panel is mounted in the main sidebar between chat and announcements.
- Sidebar user card opens the personal panel.
- Friend code is visible in the personal panel and copy feedback changes to `已複製`.
- Cloud drive account-scoped share with a non-friend target returns a clean permission message instead of the frontend `Cannot create property 'textContent' on string` TypeError.
- File share links support browser preview and download.
- Share management rows expose an edit button and the edit form opens.
- Share link copy actions show `已完成複製` below the clicked button.
- Shared file preview page shows the browser preview button and renders text content.
- Mobile profile panel did not show horizontal overflow at 390px width.

Evidence:

- `/tmp/hackme_web_qa_20260516_share_profile_5010b/share_profile_high_pressure.json`
- `/tmp/hackme_web_qa_20260516_share_profile_5010b/member_probe/member_probe.json`

## Pressure Results

Custom high-pressure probe:

- 90 mixed profile/friends/share/preview reads across `test`, `test2`, and `test3`: p50 312.79 ms, p95 419.34 ms, max 562.78 ms, 0 server errors.
- 18 concurrent small uploads across three users: p50 147.67 ms, p95 445.83 ms, max 471.77 ms, 0 server errors.
- Server log scan found no `Traceback`, `500`, `Internal Server Error`, or `Cannot create property`.
- Server RSS after the run was about 117 MB.

## Notes

`member_probe.py` still reports `video upload password share unlock playback` as high because it expects immediate shared playback. Current video behavior intentionally keeps shared video unavailable until HLS processing is ready, so this probe needs to wait for HLS-ready notification/state before treating that path as failed.

The first attempt to run `test_for_develop.sh` inside the sandbox misreported local ports as occupied because socket creation was blocked. Running the dev server outside the network sandbox started cleanly.
