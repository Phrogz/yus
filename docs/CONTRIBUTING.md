# How to Contribute to YUS

YUS is in its early stages. We are actively soliciting support in the distinct stages of the data processing:

* **Play-by-Plays**: we need more than just one person providing sample commentary, to test out the sorts of things
  different people might say during a game. Record a video of some or all of a game, with your own attempt to describe
  what's happening. Things we want to hear about for indoor ultimate (not all required):
  * Offense: who picked up the disc, what team or shirt they're on; a throw type ("flick", "backhand", etc.);
     throw direction ("swing", "dump", etc.); who the throw was to; if they caught it for a score; if they dropped it;
     if the throw hit the wall/glass/netting; if the throw hit the ground before the defender could get there; if the throw
     was defended by someone.
  * Defense: who prevented a completion; if they caught the disc or just prevented the catch.
  * Subbing: each time someone subs off or onto the field, who they are.
  * Infractions: fouls and violations (e.g. "stall called"), who called it, who it was called on, whether it was contested.
  
  Please try to be consistent in how you reference a player.
    If you don't know their name, you can reference their clothing, e.g. "red shorts", "visor", "rally cap", "87".
    If you later learn their name, I _think_ it will be better if you either stay consistent with the "nickname", or
    say the association in your recording it, e.g. "Oh, red shorts is Kaia".

* **Transcription**: What's the best way to convert audio play-by-play to text? We do not care about punctuation or grammar,
  but we do care about accuracy in player names, actions specific to the sport, and timestamps. Help investigate different
  ASR model providers, feeding in sport terms and player names? Or train a custom model that works well for a single sport!
  * Test play-by-play video and audio files are available in [this shared Google Drive][0].
  * Presently the output from Google Speech (with a particular model and adaptation) for these will be added there.
  * Ground truth expected transcription results are (slowly) being added to `tests/data` directory.

* **User Experience**: In a web app on mobile, how can we help commentators know player names, or later associate their
  description with specific players?

* **Event Extraction**: What's the best way to convert a transcript into a series of structured events?
  Given some ground-truth transcriptions, see if you can come up with algorithms or LLMs that produce the desired output!
  
  Note that the commentary is fast and varied:

  _"Tristan picks it up flick swing to Joe he dumps to Emily swings to Matt cross field to Tristan hammer_
  _huck into the end zone, off the wall, caught by Joe for the score."_

  * Test transcriptions, and the expected events from them are available in the `tests/data` directory.

* **Event Unification**: Given two event streams from two commentators, we need logic to merge them, figure out how to
  unify "Pikachu" and "Matt" and "Whitlock", resolve cases where one commentator did not see who caught it but the other
  did, merging two events that describe the same action, etc.

  * Test event streams and their expected unified output will be in the `tests/data` directory.  
    _(Currently there's only one test event stream, where unification simply assigns the right names to some players.)_

* **Stats**: Given a stream of events with timestamps, player and team names, throw types, outcomes, brainstorm on what
  sorts of stats you'd like to see and play with.
  * Stat ideas are currently captured on the [YUS Stats][5] issue.

* **Visualizations**: Making pretty web pages that show the stats in a useful way.

## Getting Started with the Code

YUS is written in Python. To contribute you need some version of Python, `git`, `uv`, and (strongly suggested) VS Code:

* [git][1]
* [vscode][2]
* [uv][3] (for Windows, use Linux standalone installer in WSL2)

The easiest way to start is to fork the repository on GitHub...  
<https://github.com/Phrogz/yus/fork>  
...and then clone it and play around:

```bash
# Clone the repository
git clone https://github.com/your-account-here/yus.git
cd yus

# Install (just for this project) the Python and packages we need
uv venv
source .venv/bin/activate
uv sync

# Open the workspace in VS Code
code yus.code-workspace
```

Once you've done work that you feel is good (or ready for discussion), push your work to GitHub and
[create a Pull Request from your fork][4].

### No, Fork You!

Not interested in forking? Want to be a contributor on the official repo? That's fine!
Send Gavin a message (303.408.0101) or a email (gavin@phrogz.net) with your GitHub username, and he'll
add you to the contributor list so you can help maintain the project.
The `main` branch is locked down, so you'll need to create your own branch(es) in git for your work
and then [create a local Pull Request][6] to get your work reviewed and merged in.

[0]: https://drive.google.com/drive/folders/19bUv4njVPwTfGE1zKe0FUus2DssEI4W1?usp=sharing
[1]: https://git-scm.com/downloads
[2]: https://code.visualstudio.com/Download
[3]: https://docs.astral.sh/uv/getting-started/installation/
[4]: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request-from-a-fork
[5]: https://github.com/Phrogz/yus/issues/1
[6]: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request
