#!/bin/bash
# Supabase Schema Deployment Script
# Run this to deploy the complete schema to your Supabase instance

set -e  # Exit on any error

echo "🚀 Starting Supabase Schema Deployment..."

# Check if Supabase CLI is available
if ! command -v supabase &> /dev/null; then
    echo "❌ Supabase CLI not found. Please install it first:"
    echo "   npm install -g supabase"
    exit 1
fi

# Check if we're in the project root
if [ ! -f "schema/000_baseline.sql" ]; then
    echo "❌ Please run this script from the project root directory"
    exit 1
fi

echo "📋 Step 1: Verify current schema state..."
# You can run this manually first: supabase db reset --db-url YOUR_DATABASE_URL

echo "📋 Step 2: Deploy baseline schema (000_baseline.sql)..."
supabase db push --file schema/000_baseline.sql --db-url "${DATABASE_URL}"

echo "📋 Step 3: Apply migrations in numeric order..."
# Apply all NNN_*.sql files in order (014, 015, 016)
for migration_file in schema/[0-9][0-9][0-9]_*.sql; do
    if [ "$migration_file" != "schema/000_baseline.sql" ]; then
        echo "Applying migration: $(basename "$migration_file")"
        supabase db push --file "$migration_file" --db-url "${DATABASE_URL}"
    fi
done

echo "📋 Step 4: Verify deployment..."
supabase db push --file scripts/verify_schema_state.sql --db-url "${DATABASE_URL}"

echo "✅ Schema deployment complete!"
echo ""
echo "Next steps:"
echo "1. Run bootstrap setup: python scripts/bootstrap.py"
echo "2. Generate journal: python generate_journal.py --force"
