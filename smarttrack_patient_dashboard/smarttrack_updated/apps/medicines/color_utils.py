"""Medicine color helpers for quick presets and custom values."""

QUICK_COLORS = [
    ('blue', 'Blue', '#3b82f6'),
    ('green', 'Green', '#10b981'),
    ('red', 'Red', '#ef4444'),
    ('purple', 'Purple', '#8b5cf6'),
    ('yellow', 'Yellow', '#eab308'),
]

NAMED_COLORS = {
    'orange': '#f97316',
    'skyblue': '#0ea5e9',
    'pink': '#ec4899',
    'brown': '#92400e',
    'black': '#1e293b',
    'teal': '#14b8a6',
    'cyan': '#06b6d4',
    'gray': '#64748b',
    'grey': '#64748b',
    'lime': '#84cc16',
    'indigo': '#6366f1',
}


def normalize_medicine_color(raw_value, quick_choice='blue', custom_value=''):
    """Resolve posted color from quick preset or custom input."""
    if raw_value == 'custom':
        custom = (custom_value or '').strip().lower()
        if not custom:
            return quick_choice or 'blue'
        if custom.startswith('#') and len(custom) in (4, 7):
            return custom
        if custom in NAMED_COLORS:
            return custom
        if custom in dict(QUICK_COLORS):
            return custom
        return custom[:30]
    return (raw_value or quick_choice or 'blue')[:30]


def medicine_color_style(color):
    """Return inline CSS background/text colors for a medicine label."""
    presets = {
        'blue': ('#dbeafe', '#2563eb'),
        'green': ('#d1fae5', '#059669'),
        'red': ('#fee2e2', '#dc2626'),
        'purple': ('#ede9fe', '#7c3aed'),
        'yellow': ('#fef9c3', '#ca8a04'),
        'orange': ('#ffedd5', '#ea580c'),
        'skyblue': ('#e0f2fe', '#0284c7'),
        'pink': ('#fce7f3', '#db2777'),
        'brown': ('#fef3c7', '#92400e'),
        'black': ('#f1f5f9', '#0f172a'),
        'teal': ('#ccfbf1', '#0d9488'),
        'cyan': ('#cffafe', '#0891b2'),
        'gray': ('#f1f5f9', '#475569'),
        'grey': ('#f1f5f9', '#475569'),
        'lime': ('#ecfccb', '#65a30d'),
        'indigo': ('#e0e7ff', '#4f46e5'),
    }
    if color in presets:
        bg, fg = presets[color]
        return f'background-color:{bg};color:{fg}'
    if color and color.startswith('#'):
        return f'background-color:{color}22;color:{color}'
    return 'background-color:#fef3c7;color:#b45309'


def medicine_color_classes(color):
    """Tailwind classes for known presets; empty string for custom colors."""
    mapping = {
        'blue': 'bg-blue-100 text-blue-600',
        'green': 'bg-emerald-100 text-emerald-600',
        'red': 'bg-red-100 text-red-600',
        'purple': 'bg-violet-100 text-violet-600',
        'yellow': 'bg-yellow-100 text-yellow-700',
        'orange': 'bg-orange-100 text-orange-600',
        'skyblue': 'bg-sky-100 text-sky-600',
        'pink': 'bg-pink-100 text-pink-600',
        'brown': 'bg-amber-100 text-amber-800',
        'black': 'bg-slate-200 text-slate-800',
        'teal': 'bg-teal-100 text-teal-600',
        'cyan': 'bg-cyan-100 text-cyan-600',
        'gray': 'bg-slate-100 text-slate-600',
        'grey': 'bg-slate-100 text-slate-600',
        'lime': 'bg-lime-100 text-lime-700',
        'indigo': 'bg-indigo-100 text-indigo-600',
    }
    return mapping.get(color, '')
