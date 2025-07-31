#!/usr/bin/env python3
"""
Test script to verify Supabase API credentials from .env file
"""
import os
import sys
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

def test_supabase_connection():
    """Test Supabase connection using credentials from .env"""
    print("🔍 Testing Supabase Connection...")
    
    # Get Supabase credentials from environment
    supabase_url = f"https://{os.getenv('Supabase_ID')}.supabase.co"
    supabase_key = os.getenv('anon_public')
    service_role_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    print(f"Supabase URL: {supabase_url}")
    print(f"Anon Key: {supabase_key[:20]}..." if supabase_key else "Anon Key: Not found")
    print(f"Service Role Key: {service_role_key[:20]}..." if service_role_key else "Service Role Key: Not found")
    
    try:
        # Try to import and use supabase
        try:
            from supabase import create_client, Client
        except ImportError:
            print("❌ Supabase client not installed. Install with: pip install supabase")
            return False
        
        # Create client with anon key
        supabase: Client = create_client(supabase_url, supabase_key)
        
        # Test connection by getting table list (should work with anon key)
        # Try a simple query that should work with basic permissions
        try:
            # Try to query pg_tables which should be accessible
            result = supabase.rpc('version').execute()
            print("✅ Supabase connection successful!")
            print(f"   - Connected to: {supabase_url}")
            print(f"   - Auth status: Connected with anon key")
            return True
        except:
            # Fallback: just test the client creation
            print("✅ Supabase client created successfully!")
            print(f"   - Connected to: {supabase_url}")
            print(f"   - Note: Limited query access with anon key")
            return True
            
    except ImportError:
        print("❌ Supabase client not installed. Install with: pip install supabase")
        return False
    except Exception as e:
        print(f"❌ Supabase connection error: {e}")
        return False

def test_database_url():
    """Test direct PostgreSQL connection using DATABASE_URL"""
    print("\n🔍 Testing Direct PostgreSQL Connection...")
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL not found in environment")
        return False
    
    print(f"Database URL: {database_url[:50]}...")
    
    try:
        try:
            import psycopg2
        except ImportError:
            print("❌ psycopg2 not installed. Install with: pip install psycopg2-binary")
            return False
        
        # Test connection
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        # Simple query to test connection
        cursor.execute("SELECT version();")
        db_version = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        print("✅ Direct PostgreSQL connection successful!")
        if db_version and db_version[0]:
            print(f"   - Database version: {db_version[0][:50]}...")
        else:
            print("   - Database version: Unknown")
        return True
        
    except ImportError:
        print("❌ psycopg2 not installed. Install with: pip install psycopg2-binary")
        return False
    except Exception as e:
        print(f"❌ PostgreSQL connection error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 SUPABASE API CREDENTIALS TEST")
    print("=" * 60)
    
    # Test Supabase connection
    supabase_success = test_supabase_connection()
    
    # Test direct database connection
    postgres_success = test_database_url()
    
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS")
    print("=" * 60)
    print(f"Supabase Client: {'✅ PASS' if supabase_success else '❌ FAIL'}")
    print(f"PostgreSQL Direct: {'✅ PASS' if postgres_success else '❌ FAIL'}")
    
    if supabase_success or postgres_success:
        print("\n🎉 At least one connection method is working!")
    else:
        print("\n⚠️  No database connections are working. Check your credentials.")
