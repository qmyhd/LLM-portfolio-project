"""
SEC 13F XML Parser and Filter
=============================

This module provides tools to parse SEC 13F XML filings (Information Tables)
and filter them against a local portfolio of positions.

Features:
1. XML Parsing with Namespace handling
2. Filtering against local positions (CUSIP matching)
3. SQL Insert generation for institutional_holdings table

Usage:
    from src.etl.sec_13f_parser import parse_sec_13f_xml, filter_for_my_portfolio, generate_sql_inserts

    # 1. Parse XML
    df = parse_sec_13f_xml('path/to/13f.xml')

    # 2. Filter
    my_positions = pd.DataFrame({'cusip': ['123456789'], 'my_avg_cost': [100.0]})
    relevant, summary = filter_for_my_portfolio(df, my_positions)

    # 3. Generate SQL
    sql_statements = generate_sql_inserts(relevant, manager_cik='12345', manager_name='Fund X', filing_date='2025-01-01')
"""

import pandas as pd
import xml.etree.ElementTree as ET
from typing import List, Tuple, Optional, Dict


def parse_sec_13f_xml(file_path: str) -> pd.DataFrame:
    """
    Parses a local SEC 13F XML file into a flat Pandas DataFrame.
    Handles XML namespaces automatically to ensure data is found.

    Args:
        file_path: Path to the XML file

    Returns:
        pd.DataFrame: Parsed data with columns [issuer, cusip, value_x1000, shares, share_type, put_call, discretion]
    """
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except Exception as e:
        print(f"Error parsing XML file {file_path}: {e}")
        return pd.DataFrame()

    # Define namespaces explicitly (SEC standard)
    namespaces = {
        "ns": "http://www.sec.gov/edgar/document/thirteenf/informationtable",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    }

    rows = []

    # Iterate over all infoTable entries
    # Note: Some files might use different namespaces or none, but this targets the standard SEC format
    for info in root.findall("ns:infoTable", namespaces):
        # Helper to safely get text from a child tag
        def get_val(tag):
            node = info.find(f"ns:{tag}", namespaces)
            return node.text if node is not None else None

        # Extract nested share amount
        shares_node = info.find("ns:shrsOrPrnAmt", namespaces)
        ssh_prnamt = (
            shares_node.find("ns:sshPrnamt", namespaces).text
            if shares_node is not None
            else "0"
        )
        ssh_prnamt_type = (
            shares_node.find("ns:sshPrnamtType", namespaces).text
            if shares_node is not None
            else None
        )

        row = {
            "issuer": get_val("nameOfIssuer"),
            "cusip": get_val("cusip"),
            "value_x1000": get_val("value"),  # Usually in thousands
            "shares": ssh_prnamt,
            "share_type": ssh_prnamt_type,
            "put_call": get_val("putCall"),  # Matches 'Put', 'Call', or None
            "discretion": get_val("investmentDiscretion"),
        }
        rows.append(row)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    # Clean numeric columns
    df["value_x1000"] = pd.to_numeric(df["value_x1000"], errors="coerce").fillna(0)
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0)

    return df


def filter_for_my_portfolio(
    sec_dataframe: pd.DataFrame, my_positions_df: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Filters the parsed SEC data to only show institutional activity
    on stocks found in 'my_positions_df'.

    Args:
        sec_dataframe: The output from parse_sec_13f_xml()
        my_positions_df: A dataframe with a 'cusip' column (and optionally 'ticker', 'my_avg_cost').

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (relevant_holdings, summary)
    """
    if sec_dataframe.empty or my_positions_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 1. Normalize identifiers (Example: CUSIP)
    # Ensure CUSIPs are strings and 9 characters (sometimes leading zeros are dropped)
    if "cusip" in sec_dataframe.columns:
        sec_dataframe["cusip"] = sec_dataframe["cusip"].astype(str).str.zfill(9)

    if "cusip" in my_positions_df.columns:
        my_positions_df["cusip"] = my_positions_df["cusip"].astype(str).str.zfill(9)
    else:
        raise ValueError("my_positions_df must contain a 'cusip' column")

    # 2. Perform Inner Join
    # This drops all rows from the SEC data that don't match your portfolio
    # Select only needed columns from your data to avoid duplicates if they exist
    cols_to_keep = ["cusip"]
    if "ticker" in my_positions_df.columns:
        cols_to_keep.append("ticker")
    if "my_avg_cost" in my_positions_df.columns:
        cols_to_keep.append("my_avg_cost")

    relevant_holdings = pd.merge(
        sec_dataframe, my_positions_df[cols_to_keep], on="cusip", how="inner"
    )

    # 3. Aggregation (Optional: See who owns the most of YOUR stocks)
    summary = pd.DataFrame()
    if not relevant_holdings.empty:
        summary = (
            relevant_holdings.groupby("issuer")
            .agg({"value_x1000": "sum", "shares": "sum"})
            .sort_values("value_x1000", ascending=False)
        )

    return relevant_holdings, summary


def generate_sql_inserts(
    df: pd.DataFrame, manager_cik: str, manager_name: str, filing_date: str
) -> List[str]:
    """
    Generates SQL INSERT statements for the institutional_holdings table.

    Args:
        df: Filtered DataFrame containing holdings
        manager_cik: CIK of the institutional manager
        manager_name: Name of the institutional manager
        filing_date: Date of the filing (YYYY-MM-DD)

    Returns:
        List[str]: List of SQL INSERT statements
    """
    statements = []

    for _, row in df.iterrows():
        # Calculate full value (value_x1000 is in thousands)
        value_usd = int(row["value_x1000"] * 1000)

        # Handle booleans for put/call
        put_call = str(row.get("put_call", "")).upper()
        is_put = "TRUE" if put_call == "PUT" else "FALSE"
        is_call = "TRUE" if put_call == "CALL" else "FALSE"

        # Escape strings
        issuer = str(row["issuer"]).replace("'", "''")
        mgr_name = str(manager_name).replace("'", "''")
        ticker = str(row.get("ticker", "")).replace("'", "''")

        sql = f"""
        INSERT INTO institutional_holdings (
            filing_date, manager_cik, manager_name, 
            cusip, ticker, company_name, 
            value_usd, shares, share_type, 
            is_put, is_call
        ) VALUES (
            '{filing_date}', '{manager_cik}', '{mgr_name}',
            '{row['cusip']}', '{ticker}', '{issuer}',
            {value_usd}, {int(row['shares'])}, '{row['share_type']}',
            {is_put}, {is_call}
        );
        """
        statements.append(sql.strip())

    return statements
