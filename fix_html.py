import re

# Read the HTML file
with open('templates/file-inspector.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the entire <style>...</style> block with a CSS link
pattern = r'<style>.*?</style>'
replacement = '<link rel="stylesheet" href="css/styles.css">'
new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

# Write back
with open('templates/file-inspector.html', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('✓ CSS extraction complete! Replaced <style> block with external link.')
