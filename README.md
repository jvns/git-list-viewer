# git list viewer

This is an alternative viewer for the Git mailing list at https://lore.kernel.org/git

I just made it for myself to use to be able to navigate the mailing list more easily.
In principle you could use it for other mailing lists that use [public inbox](https://public-inbox.org/README.html)

Some caveats:

- Some of the code is LLM generated and not very carefully thought through.
  Specifically the search is not very good at all.
- It only includes "newer" emails from https://lore.kernel.org/git/1, not the
  older ones from https://lore.kernel.org/git/0

## Developing

First clone the Git repository which contains the Git mailing list emails

```
export GIT_REPO_PATH=/some/path
git clone --mirror https://lore.kernel.org/git/1 GIT_REPO_PATH
```

Then you should be able to run it with:

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

You can also use the PORT enviroment variable to run it on a different port
