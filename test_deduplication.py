#!/usr/bin/env python3
"""
Test script to verify the deduplication logic works correctly
"""

import json
import os
import sys
import tempfile
import shutil

# Add the repo to path
sys.path.insert(0, '/tmp/bidding-notifier')

# Import the functions from push_combined
from push_combined import load_pushed_records, save_pushed_records, is_bid_pushed, mark_bid_pushed, get_bid_hash, PUSHED_RECORDS_FILE

def test_deduplication():
    """Test the deduplication logic"""
    
    # Create a temporary directory for testing
    test_dir = tempfile.mkdtemp()
    original_dir = os.getcwd()
    
    try:
        os.chdir(test_dir)
        
        print("=" * 60)
        print("🧪 测试去重逻辑")
        print("=" * 60)
        
        # Test 1: Empty records
        print("\n📋 Test 1: 空记录文件")
        records = load_pushed_records()
        assert records == {"hashes": [], "urls": []}, "Empty records should have empty hashes and urls"
        print("✅ 空记录加载正确")
        
        # Test 2: Mark some bids as pushed
        print("\n📋 Test 2: 标记招标为已推送")
        mark_bid_pushed("Test Bid 1", "https://example.com/detail/1", records)
        mark_bid_pushed("Test Bid 2", "https://example.com/detail/2", records)
        mark_bid_pushed("Test Bid 3", "", records)  # No URL
        
        assert len(records["hashes"]) == 3, f"Expected 3 hashes, got {len(records['hashes'])}"
        assert len(records["urls"]) == 2, f"Expected 2 URLs, got {len(records['urls'])}"
        print("✅ 标记已推送正确")
        
        # Test 3: Save and reload
        print("\n📋 Test 3: 保存并重新加载")
        save_pushed_records(records)
        assert os.path.exists(PUSHED_RECORDS_FILE), "File should exist after save"
        
        records2 = load_pushed_records()
        assert len(records2["hashes"]) == 3, f"Expected 3 hashes after reload, got {len(records2['hashes'])}"
        print("✅ 保存和重新加载正确")
        
        # Test 4: Check deduplication
        print("\n📋 Test 4: 去重检查")
        assert is_bid_pushed("Test Bid 1", "https://example.com/detail/1", records2) == True, "Bid 1 should be marked as pushed"
        assert is_bid_pushed("Test Bid 2", "", records2) == True, "Bid 2 should be marked as pushed (by title hash)"
        assert is_bid_pushed("New Bid", "https://example.com/detail/99", records2) == False, "New bid should not be marked as pushed"
        print("✅ 去重检查正确")
        
        # Test 5: Simulate the issue - file should persist
        print("\n📋 Test 5: 模拟多次运行（持久化测试）")
        
        # First run
        records_run1 = load_pushed_records()
        new_bids_run1 = [
            {"title": "Bid A", "url": "https://example.com/a"},
            {"title": "Bid B", "url": "https://example.com/b"},
        ]
        for bid in new_bids_run1:
            if not is_bid_pushed(bid["title"], bid["url"], records_run1):
                mark_bid_pushed(bid["title"], bid["url"], records_run1)
        save_pushed_records(records_run1)
        
        # Second run (simulating a new workflow run)
        records_run2 = load_pushed_records()
        all_bids = [
            {"title": "Bid A", "url": "https://example.com/a"},  # Already pushed
            {"title": "Bid B", "url": "https://example.com/b"},  # Already pushed
            {"title": "Bid C", "url": "https://example.com/c"},  # New
        ]
        
        new_count = 0
        for bid in all_bids:
            if not is_bid_pushed(bid["title"], bid["url"], records_run2):
                new_count += 1
                mark_bid_pushed(bid["title"], bid["url"], records_run2)
        
        save_pushed_records(records_run2)
        
        assert new_count == 1, f"Expected 1 new bid in run 2, got {new_count}"
        # Total hashes: 3 (from Test 2) + 2 (new_bids_run1) + 1 (Bid C from all_bids) = 6
        assert len(records_run2["hashes"]) == 6, f"Expected 6 total hashes, got {len(records_run2['hashes'])}"
        print("✅ 持久化测试通过 - 已推送的招标不会被重复推送")
        
        print("\n" + "=" * 60)
        print("🎉 所有测试通过！")
        print("=" * 60)
        
    finally:
        os.chdir(original_dir)
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    test_deduplication()

