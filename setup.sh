#!/bin/bash
echo "Installing Halal Stock Checker dependencies..."
pip install -r requirements.txt
echo "Initializing database tables..."
python init_db.py
echo "Done! Run with: streamlit run app.py"
