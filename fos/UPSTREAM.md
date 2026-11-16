# FOS Upstream

FOS is integrated into GAWorld under `fos/` using a squashed Git subtree.

## Upstream repository

https://github.com/ZJU-Computational-Social-Science-Lab/fos.git

## Imported revision

Branch: `main`
Commit: a76ea5566cc7ec88d421f92ada6a0da034200895

## Import strategy

FOS is imported with:

```
git subtree --squash
```

The full FOS Git history is intentionally kept in the upstream FOS repository
rather than duplicated inside GAWorld.

## Updating from upstream

Before updating:

1. ensure the GAWorld integration branch is clean;
2. fetch/check the current FOS `main`;
3. record the upstream SHA being imported.

Typical update command:

```
git subtree pull \
  --prefix=fos \
  https://github.com/ZJU-Computational-Social-Science-Lab/fos.git \
  main \
  --squash
```

Any GAWorld-specific modifications inside `fos/` must be reviewed for conflicts
before pulling future upstream changes.
