#!/bin/sh
set -eu
mkdir -p /telegram/temp
exec telegram-bot-api --local --http-port=8081 --dir=/telegram --temp-dir=/telegram/temp --verbosity=0
