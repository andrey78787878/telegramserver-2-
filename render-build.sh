#!/bin/bash
pip install --upgrade pip
pip uninstall python-telegram-bot -y
pip install -r requirements.txt --no-cache-dir
