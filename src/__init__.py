"""
LLM Portfolio Project - Core Package
=====================================

A data-driven portfolio journal that integrates brokerage data, market information,
and social sentiment analysis to generate comprehensive trading insights using LLMs.

Core Modules:
- config: Centralized configuration management
- database: Dual SQLite/PostgreSQL database layer
- db: SQLAlchemy engine with connection pooling
- data_collector: Financial data collection and storage
- journal_generator: LLM-powered journal generation
- logging_utils: Discord message logging and processing
- twitter_analysis: Social sentiment analysis
"""

__version__ = "1.0.0"
__author__ = "LLM Portfolio Project"
