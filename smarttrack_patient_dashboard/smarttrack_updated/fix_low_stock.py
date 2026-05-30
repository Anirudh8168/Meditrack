import re

with open('templates/dashboard/patient/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the low_stock block and add the link
start_idx = content.find('{% elif low_stock %}')
if start_idx != -1:
    end_idx = content.find('{% endif %}', start_idx)
    if end_idx != -1:
        # Find the last </div> before this endif
        div_idx = content.rfind('</div>', start_idx, end_idx)
        if div_idx != -1:
            link = '\n  <p class="text-xs text-amber-600 mt-2">Please consider refilling soon. <a href="#" class="underline font-semibold find-pharmacy-trigger">Find nearby pharmacy &rarr;</a></p>'
            content = content[:div_idx+6] + link + content[div_idx+6:]

with open('templates/dashboard/patient/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
