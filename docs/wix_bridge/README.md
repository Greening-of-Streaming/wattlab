# Open WattLab findings on the GoS website (CR-087)

The GoS website (Wix) shows OWL's findings from its own copy, so the page keeps
working when OWL is offline.

```
OWL  /findings.json  ──(Wix pulls hourly)──▶  Wix collection OwlFindings  ──▶  findings page
```

- **OWL publishes, Wix pulls.** OWL holds no Wix password or key. The feed is
  read-only and public: https://wattlab.greeningofstreaming.org/findings.json
- **Only reviewed findings cross over:** Lab-checked or Validated. Pressing
  "Lab validation" on OWL publishes a finding to the website within the hour;
  withdrawing it removes it at the next sync.
- **If OWL is down, or sends something malformed, nothing on the website
  changes.** An empty feed never deletes findings already on the site.
- **Early signals** arrive without a headline number or summary, as on OWL.

## Setting it up in Wix (about 30 minutes, once)

1. **Turn on Dev Mode** (Velo) in the site editor.
2. **Create a CMS collection** with the ID `OwlFindings`.
   - Permissions: anyone can read; only admins can add, update or delete.
   - Fields, by field key and type:

     | Field key | Type |
     |---|---|
     | `title` (exists already) | Text |
     | `slug`, `whyItMatters`, `summary`, `keyNumber` | Text |
     | `confidence`, `confidenceLabel`, `reviewLabel` | Text |
     | `question`, `questionLabel`, `stages` | Text |
     | `firstMeasured`, `lastRefined`, `owlUrl` | Text |
     | `earlySignal` | Boolean |
     | `repeats`, `sortOrder` | Number |
     | `syncedAt` | Date and time |
3. **Add the backend code.** In the Backend section of the code panel, add
   `backend/owlSync.js` and `backend/jobs.config` from this folder, unchanged.
   The job runs at a quarter past every hour, and only on the published site.
4. **Run it once by hand** so the page has data: open `owlSync.js`, run
   `syncOwlFindings` with the test-run button, and check the log says
   "OWL sync: N saved".
5. **Build the page.** Add a dataset connected to `OwlFindings`, sorted by
   `sortOrder` ascending, and a repeater connected to it. Bind the text
   elements to the fields you want: at least `title`, `whyItMatters`,
   `keyNumber`, `confidenceLabel` and `reviewLabel`.
6. **Paste `findings-page.js`** into the page's code and rename the element IDs
   to match yours. It hides empty numbers, marks early signals, and links each
   card to its OWL page, or hides the link for findings that have no public
   page yet.
7. **Publish the site.**

Worth showing on the page: "Source: Open WattLab, the measurement lab of
Greening of Streaming", and a link to https://wattlab.greeningofstreaming.org.

## Checking it

- The feed: open the URL above in a browser.
- The sync: Wix's Site Monitoring logs show one "OWL sync" line an hour, or an
  "OWL sync skipped" warning when OWL was unreachable.

The code uses Velo's `wix-fetch` and `wix-data` modules. It was tested outside
Wix against the real feed (see `CHANGE_REQUESTS.md`, CR-087); the first run in
Wix is the real check.
