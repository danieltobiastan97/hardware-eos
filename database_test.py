#!/usr/bin/env python
"""Test ProductEOSRepo with dynamic support tiers and date parsing."""
from models_copy import init_database, ProductEOSRepo, parse_date
from datetime import date
import json
import sys

def test_date_parser():
    """Test the date parser utility function."""
    print("=" * 70)
    print("Test 0: Date Parser Utility")
    print("=" * 70)
    try:
        # Test 1: String input (ISO format)
        result1 = parse_date("2024-07-31")
        assert isinstance(result1, date), "Should return date object"
        assert result1 == date(2024, 7, 31), "Should parse ISO string correctly"
        print(f"✓ String parse: '2024-07-31' → {result1}")
        
        # Test 2: Date object input
        input_date = date(2023, 1, 15)
        result2 = parse_date(input_date)
        assert result2 == input_date, "Should return same date object"
        print(f"✓ Date object: {input_date} → {result2}")
        
        # Test 3: Invalid format should raise error
        try:
            parse_date("31-07-2024")  # Wrong format
            print(f"✗ Should have raised ValueError for invalid format")
            return False
        except ValueError as e:
            print(f"✓ Invalid format caught: {e}")
        
        # Test 4: Invalid type should raise error
        try:
            parse_date(12345)  # Invalid type
            print(f"✗ Should have raised TypeError for invalid type")
            return False
        except TypeError as e:
            print(f"✓ Invalid type caught: {e}")
        
        print()
        
    except Exception as e:
        print(f"✗ Date parser test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

def test_product_eos_repo():
    """Test the ProductEOSRepo functions with the new schema."""
    
    print("=" * 70)
    print("   ProductEOS Database Test Suite with Date Parsing")
    print("=" * 70)
    print()
    
    # Initialize database
    print("Initializing database...")
    try:
        engine, session = init_database("sqlite:///asset_cache.db")
        print("✓ Database initialized successfully")
        print()
    except Exception as e:
        print(f"✗ Failed to initialize database: {e}")
        return False
    
    # Create repo instance
    repo = ProductEOSRepo(session)
    
    # ========== TEST 1: add_product with STRING dates and dynamic support tiers ==========
    print("=" * 70)
    print("Test 1: add_product() with STRING dates and dynamic tiers")
    print("=" * 70)
    try:
        # Create Cisco IOS XE product using STRING dates (like from JSON)
        product1 = repo.add_product(
            name="Cisco IOS XE 16.12.x (Amsterdam)",
            summary="Cisco IOS XE 16.12.x reached its final milestone for software maintenance on July 31, 2022, with vulnerability support ending on July 31, 2024.",
            hardware_software="Software",
            support_model="Version-Based",
            eos_date="2024-07-31",  # ← STRING input (like from JSON)
            source_urls=["https://www.cisco.com/c/en/us/products/collateral/ios-nx-os-software/ios-xe-16/eos-eol-notice-c51-742899.html"],
            confidence=1.0
        )
        print(f"✓ Created product 1 with STRING date: {product1.name}")
        print(f"  EOS Date stored as: {product1.eos_date} (type: {type(product1.eos_date).__name__})")
        
        # Add support tiers using STRING dates
        tier1 = repo.add_support_tier(
            product_id=product1.id,
            tier_name="End of SW Maintenance Releases",
            end_date="2022-07-31"  # ← STRING input
        )
        print(f"  ✓ Added tier 1 with STRING date: {tier1.tier}")
        
        tier2 = repo.add_support_tier(
            product_id=product1.id,
            tier_name="End of Vulnerability/Security Support",
            end_date="2024-07-31"  # ← STRING input
        )
        print(f"  ✓ Added tier 2 with STRING date: {tier2.tier}")
        
        # Create another product with date() objects (traditional way)
        product2 = repo.add_product(
            name="Windows Server 2016",
            summary="Windows Server 2016 mainstream support ended January 11, 2022, with extended support ending January 12, 2027.",
            hardware_software="Software",
            support_model="Product-Based",
            eos_date=date(2027, 1, 12),  # ← date() object (traditional)
            source_urls=["https://learn.microsoft.com/en-us/windows-server/windows-server-2016"],
            confidence=0.95
        )
        print(f"\n✓ Created product 2 with date() object: {product2.name}")
        
        # Add tiers with both STRING and date() objects
        repo.add_support_tier(product2.id, "Mainstream Support", "2022-01-11")  # String
        repo.add_support_tier(product2.id, "Extended Support", date(2027, 1, 12))  # date() object
        repo.add_support_tier(product2.id, "Critical Updates Only", "2025-01-12")  # String
        print(f"  ✓ Added 3 tiers (mix of STRING and date() objects)")
        
        print()
        
    except Exception as e:
        print(f"✗ add_product() failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # ========== TEST 2: get_product_by_name ==========
    print("=" * 70)
    print("Test 2: get_product_by_name()")
    print("=" * 70)
    try:
        result = repo.get_product_by_name("Cisco")
        if result:
            print(f"✓ Found product: {result.name}")
            print(f"  Hardware/Software: {result.hardware_software}")
            print(f"  EOS Date: {result.eos_date}")
            print(f"  Support Tiers: {len(result.support_tiers)}")
        else:
            print(f"✗ Did not find 'Cisco'")
            return False
        
        result2 = repo.get_product_by_name("Windows")
        if result2:
            print(f"\n✓ Found product: {result2.name}")
            print(f"  Support Tiers: {len(result2.support_tiers)}")
        else:
            print(f"✗ Did not find 'Windows'")
            return False
        
        print()
        
    except Exception as e:
        print(f"✗ get_product_by_name() failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # ========== TEST 3: get_product_tiers (dynamic tiers) ==========
    print("=" * 70)
    print("Test 3: get_product_tiers() - Dynamic tier retrieval")
    print("=" * 70)
    try:
        product = repo.get_product_by_name("Cisco")
        tiers = repo.get_product_tiers(product.id)
        print(f"✓ Product '{product.name}' has {len(tiers)} support tiers:")
        for i, tier in enumerate(tiers, 1):
            print(f"  {i}. {tier.tier} - Ends: {tier.end_date}")
        
        product2 = repo.get_product_by_name("Windows")
        tiers2 = repo.get_product_tiers(product2.id)
        print(f"\n✓ Product '{product2.name}' has {len(tiers2)} support tiers:")
        for i, tier in enumerate(tiers2, 1):
            print(f"  {i}. {tier.tier} - Ends: {tier.end_date}")
        
        print()
        
    except Exception as e:
        print(f"✗ get_product_tiers() failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # ========== TEST 4: export_as_json ==========
    print("=" * 70)
    print("Test 4: export_as_json() - JSON export with parsed dates")
    print("=" * 70)
    try:
        product = repo.get_product_by_name("Cisco")
        json_output = repo.export_as_json(product.id)
        
        print(f"✓ Exported product as JSON:")
        print(json.dumps(json_output, indent=2))
        
        required_fields = ["Name", "Summary", "Hardware/Software", "Support Model", "EOS Date", "Support Tiers", "Source URLs", "Confidence"]
        missing_fields = [field for field in required_fields if field not in json_output]
        
        if missing_fields:
            print(f"\n✗ Missing required fields: {missing_fields}")
            return False
        else:
            print(f"\n✓ JSON structure matches required format")
        
        print()
        
    except Exception as e:
        print(f"✗ export_as_json() failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # ========== SUMMARY ==========
    print("=" * 70)
    print("   ✓ All ProductEOS tests passed!")
    print("=" * 70)
    print()
    print(f"Date Parsing Features:")
    print(f"  ✓ Accepts STRING dates (YYYY-MM-DD format)")
    print(f"  ✓ Accepts date() objects")
    print(f"  ✓ Validates ISO format")
    print(f"  ✓ Automatic conversion from JSON inputs")
    
    return True

if __name__ == '__main__':
    # Run date parser tests first
    if not test_date_parser():
        sys.exit(1)
    
    # Run main tests
    success = test_product_eos_repo()
    sys.exit(0 if success else 1)

