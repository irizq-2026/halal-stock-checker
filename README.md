# Halal Stock Checker (AAOIFI)

An iRizq.com tool for screening US stocks against AAOIFI Islamic finance standards.

## Live App

[Link to be added after deployment]

## Features

- Business sector screening (prohibits banking, alcohol, gambling, etc.)
- Financial ratio screening (debt, cash, non-halal income)
- AAOIFI-standard thresholds
- iRizq.com branded dark theme (navy + gold)
- Mobile-friendly PWA — add to iPhone Home Screen via Safari
- No login or data storage required

## How to Run Locally

```bash
git clone [your-repo-url]
cd halal-stock-checker
pip install -r requirements.txt
streamlit run app.py
```

## How to Deploy to Streamlit Cloud

1. Push this project to a GitHub repository (make sure static/ folder with logo.png and icon.png is included)
2. Go to https://share.streamlit.io
3. Sign in with GitHub
4. Click "New app"
5. Select your GitHub repo, branch: main, main file: app.py
6. Click Deploy (takes ~2 minutes)
7. Copy the public URL and share with test users

## Adding Your Logo

1. Copy your logo to: static/logo.png (use transparent PNG background)
2. Resize a square version to 180x180px → save as: static/icon.png
3. Commit both files to GitHub and redeploy

## iPhone Home Screen Instructions (share with test users)

1. Open the app URL in Safari on iPhone
2. Tap the Share button (box with arrow at bottom of screen)
3. Scroll down and tap "Add to Home Screen"
4. Tap "Add" — the iRizq Halal Stocks icon appears on your home screen
5. Open it — it runs like a native app, full screen, no browser bar

## Screening Methodology

Based on AAOIFI Shariah Standards:

- Prohibited sectors: Banking, Insurance, Gambling, Alcohol, Tobacco, Adult Entertainment, Defense/Weapons
- Debt / Market Cap must be under 33%
- Cash / Market Cap must be under 33%
- Non-permissible income / Revenue must be under 5%
- Ratios within 5% of threshold = Questionable

## Disclaimer

This tool is for educational purposes only and does not constitute a fatwa or financial advice. Always consult a qualified Islamic finance scholar for personal guidance.

## Tech Stack

- Python 3.10+
- Streamlit
- yfinance
- Deployed on Streamlit Cloud (free tier)
- Branded for iRizq.com