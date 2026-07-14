#! /bin/bash
python3 manage.py runserver 0.0.0.0:8000 &
django_pid=$!

sudo cloudflared tunnel --url http://127.0.0.1:8000 &
tunnel_pid=$!

cleanup() {
    sudo kill "$tunnel_pid" 2>/dev/null
    kill "$django_pid" 2>/dev/null
    wait 2>/dev/null
}

trap cleanup EXIT INT TERM

wait "$tunnel_pid"
