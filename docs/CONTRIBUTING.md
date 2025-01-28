# How to Contribute to YUS

YUS is a project that aims to provide detailed statistics for Ultimate games (eventually: other sports?) based on
somewhat freeform commentary. The project is in its early stages. We are actively soliciting support in the distinct
stages of the data processing:

* **Transcription**: what's the best way to convert audio commentary to text? We do not care about punctuation or grammar,
  but we do care about accuracy in player names, actions specific to the sport, and timestamps.

* **Event Extraction**: What's the best way to convert a transcript into a series of structured events?
  The commentary is fast and varied:

  _"Tristan picks it up flick swing to Joe he dumps to Emily swings to Matt crossfield to Tristan hammer huck into the_
  _endzone, off the wall, caught by Joe for the score."_

* **Event Unification**: Given two event streams from two commentators, we need logic to merge them, figure out how to
  unify "Pikachu" and "Matt" and "Whitlock", resolve cases where one commentator did not see who caught it but the other
  did, merging two events that describe the same action, etc.

* **Stats**: Given a stream of events with timestamps, player and team names, throw types, outcomes, what

* **Visualizations**: Making pretty web pages that show the stats in a useful way.

## Getting Started

YUS is written in Python. To contribute you need some version of Python, `git`, `uv`, and (strongly suggested) VS Code:

* [git](https://git-scm.com/downloads)
* [vscode](https://code.visualstudio.com/Download)
* [uv](https://docs.astral.sh/uv/getting-started/installation/) (for Windows, use Linux standalone installer in WSL2)

With those installed, from your favorite Terminal:

```bash
# Clone the repository
git clone https://github.com/Phrogz/yus.git
cd yus

# Install (just for this project) the Python and packages we need
uv venv

# Open the workspace in VS Code
code yus.code-workspace
```

## Making Changes

```bash
# Ensure you're starting from the latest code on the main branch
git checkout main
git pull

# Create a new branch for your work
git checkout -b my-new-feature

# Make your changes, then add and commit them
git add .
git commit -m "Did some work (please make better commit messages than this)"

# Occasionally test your work
# Just kidding, there aren't any tests yet. Yolo!
# uv test

# When you're feeling close to good, push your changes to GitHub
git push origin my-new-feature

# Go to GitHub and create a merge request to merge your branch into main
```
