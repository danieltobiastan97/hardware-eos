#!/usr/bin/env python3
from sqlalchemy import create_engine, text

try:
    # Use relative path for local development (host machine)
    engine = create_engine('sqlite:///./data/asset_cache.db')
    connection = engine.connect()

    print('===== DATABASE STATUS =====')
    result = connection.execute(text('SELECT COUNT(*) FROM product_eos'))
    product_count = result.fetchone()[0]
    print(f'Products: {product_count}')

    result = connection.execute(text('SELECT COUNT(*) FROM support_tier'))
    tier_count = result.fetchone()[0]
    print(f'Support Tiers: {tier_count}')

    if product_count > 0:
        print('\nProducts in database:')
        result = connection.execute(text('SELECT id, name, eos_date, support_model FROM product_eos'))
        for row in result:
            print(f'  - {row[1]} (EOS: {row[2]}, Result: {row[3]})')

    connection.close()
    print('\n✓ Database is persistent!')
except Exception as e:
    print(f'✗ Error: {e}')