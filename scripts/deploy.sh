git ls-files -z | rsync -av --files-from=- --from0 . root@dynamic-nix:/var/lib/git-list/
ssh root@dynamic-nix "systemctl restart git-list"
