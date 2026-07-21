"""Gunicorn WSGI entry point"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载 .env 环境变量
from dotenv import load_dotenv
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(dotenv_path)

from app import create_app
app = create_app()
