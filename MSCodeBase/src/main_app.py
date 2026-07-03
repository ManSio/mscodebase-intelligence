
"""Main application with typical patterns for testing."""

import os
import sys
from typing import List, Dict, Optional

class DataProcessor:
    """A data processing class with typical patterns."""

    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.data = []
        self.processed = False

    def load_data(self, file_path: str) -> bool:
        """Load data from file."""
        try:
            with open(file_path, 'r') as f:
                self.data = f.read().splitlines()
            self.processed = True
            return True
        except Exception as e:
            print(f"Error loading data: {e}")
            return False

    def process_items(self, items: List[str]) -> List[str]:
        """Process a list of items."""
        processed = []
        for item in items:
            if item.strip():
                processed.append(item.upper())
        return processed

    def save_results(self, output_path: str) -> bool:
        """Save processed results to file."""
        try:
            with open(output_path, 'w') as f:
                for item in self.data:
                    f.write(f"{item}
")
            return True
        except Exception as e:
            print(f"Error saving results: {e}")
            return False

    def get_statistics(self) -> Dict[str, int]:
        """Get processing statistics."""
        return {
            "total_items": len(self.data),
            "processed_items": len([x for x in self.data if x.strip()]),
            "empty_items": len([x for x in self.data if not x.strip()])
        }

def main():
    """Main function for testing."""
    processor = DataProcessor()

    # Test data
    test_data = ["item1", "item2", "", "item3", "item4"]

    # Process data
    processed = processor.process_items(test_data)
    print(f"Processed {len(processed)} items")

    # Get statistics
    stats = processor.get_statistics()
    print(f"Statistics: {stats}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
