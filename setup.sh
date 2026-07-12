#!/bin/bash
echo "Installing Halal Stock Checker dependencies..."
pip install -r requirements.txt
echo "Initializing database tables..."
python init_db.py
echo "Done! Run Streamlit UI with: streamlit run streamlit_app.py"
echo "Run Flask API with: gunicorn app:app"
