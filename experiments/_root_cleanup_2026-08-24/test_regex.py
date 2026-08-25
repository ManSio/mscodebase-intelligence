import sys
sys.path.insert(0, '.')

from src.mcp.tools.context_tool import GetContextTool
from src.core.di_container import create_service_collection
from pathlib import Path
import re

ROOT = Path('.').resolve()
services = create_service_collection(ROOT)
from src.mcp.tools.context_tool import GetContextTool

tool = GetContextTool(services)

mock_symbols = {
    'text': '🔍 **build_call_graph** — 1 defs\n📄 Definition: `src/core/indexing/symbol_index.py` line 480'
}

# Test regex
text = mock_symbols.get('text', '')
match = re.search(r'Definition: `([^`]+)` line (\d+)', text)
if match:
    print('Match found:', match.groups())
else:
    print('No match for Definition pattern')
    
# Try the second pattern
match2 = re.search(r'"file":\s*"([^"]+)"', text)
if match2:
    print('File pattern match:', match2.groups())
else:
    print('No file pattern match')

# Test git
match3 = re.search(r'"affected_files":\s*\[\s*"([^"]+)"', text)
print('affected_files match:', match3)

match4 = re.search(r'"file":\s*"([^"]+)"', text)
print('file pattern:', match4)

match5 = re.search(r'Definition: `([^`]+)` line', text)
print('Definition pattern:', match5)

# Test source section
source = tool._section_source('build_call_graph', mock_symbols)
if source:
    print('Source section:', source['tokens'], 'tokens')
else:
    print('Source section: None')

# Test git
git = tool._section_git('build_call_graph', mock_symbols)
if git:
    print('Git section:', git['tokens'], 'tokens')
else:
    print('Git section: None')