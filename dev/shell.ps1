# Opens a shell inside the development container, in the bench directory, as the user "frappe".
docker exec -e "TERM=xterm-256color" -u frappe -w /home/frappe/dev/frappe-bench -it munimji-dev-frappe-1 bash
