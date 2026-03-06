# bybit-final-bot

A minimal starter repository for a Bybit trading bot.

## Description

This repository contains a minimal example bot that shows how to load API credentials
from a .env file and make a simple authenticated request to Bybit using ccxt (async).

## Prerequisites

- Python 3.10+
- A Bybit API key and secret

## Setup

1. Clone the repo:
   git clone https://github.com/Tem-spec-arch/bybit-final-bot.git
   cd bybit-final-bot

2. Create a virtual environment and install dependencies:
   python -m venv .venv
   source .venv/bin/activate   # macOS/Linux
   .venv\Scripts\activate     # Windows
   pip install -r requirements.txt

3. Create a .env file in the repository root with the following contents:
   BYBIT_API_KEY=your_api_key_here
   BYBIT_API_SECRET=your_api_secret_here

4. Run the bot:
   python bot.py

## Notes

- This is a starter template. Do not run a production trading bot without thorough testing and proper risk controls.
- Keep your API keys secret and consider using restricted API permissions.
