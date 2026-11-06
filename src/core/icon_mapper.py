"""Maps lyric words to semantic icons and emojis for Visual and Fisheye Visual styles."""
import re
from typing import Dict, Optional
from src.models.lyrics import LyricsDocument


class LyricIconMapper:
    """Semantic icon mapper mapping over 800 common lyrical words to emojis and icons."""

    # Curated lyric dictionary (~800 common lyric words mapped to icons)
    WORD_MAP: Dict[str, str] = {
        # Love & Romance
        "love": "❤️", "loved": "❤️", "loves": "❤️", "loving": "❤️", "lover": "💘",
        "heart": "🫀", "hearts": "❤️", "heartbreak": "💔", "heartbroken": "💔",
        "kiss": "💋", "kisses": "💋", "kissing": "💋", "kissed": "💋",
        "hug": "🫂", "hugs": "🫂", "embrace": "🫂",
        "sweet": "🍯", "honey": "🍯", "darling": "🧸", "baby": "👶", "babe": "👶",
        "romance": "🌹", "romantic": "🌹", "crush": "💌", "passion": "🔥",
        "marry": "💍", "married": "💍", "wedding": "💒", "ring": "💍",

        # Sadness & Pain
        "cry": "😢", "crying": "😭", "cried": "😢", "cries": "😢",
        "tear": "💧", "tears": "💧", "teardrop": "💧", "weep": "😭",
        "sad": "😔", "sadness": "🥀", "sorrow": "🥀", "grief": "🥀",
        "pain": "🩹", "hurt": "💔", "hurts": "💔", "hurting": "💔",
        "ache": "💔", "bleed": "🩸", "bleeding": "🩸", "blood": "🩸",
        "break": "🔨", "broken": "💔", "broke": "💔",
        "alone": "👤", "lonely": "🥀", "loneliness": "🥀", "hollow": "🕳️",
        "empty": "🫙", "lost": "🧭", "miss": "💭", "missing": "💭",
        "goodbye": "👋", "bye": "👋", "farewell": "👋",

        # Joy, Energy & Dancing
        "happy": "😊", "happiness": "✨", "smile": "😊", "smiling": "😊", "smiled": "😊",
        "laugh": "😄", "laughing": "😄", "laughter": "😄",
        "joy": "🎉", "fun": "🎈", "party": "🪩", "celebrate": "🥂",
        "dance": "💃", "dancing": "🕺", "dancer": "💃", "dances": "💃", "groove": "🕺",
        "jump": "🦘", "jumping": "🦘", "bounce": "🏀",
        "wild": "🐆", "crazy": "🤪", "insane": "🌀", "psycho": "🔪",
        "free": "🕊️", "freedom": "🕊️", "fly": "🕊️", "flying": "🦅",
        "wing": "🪽", "wings": "🪽", "soar": "🦅", "high": "☁️",

        # Fire, Light & Elements
        "fire": "🔥", "flame": "🔥", "flames": "🔥", "burn": "🔥", "burning": "🔥", "burned": "🔥",
        "blaze": "🔥", "smoke": "💨", "ash": "🌫️", "ashes": "🌫️",
        "spark": "✨", "sparks": "✨", "firework": "🎆", "fireworks": "🎆",
        "light": "💡", "lights": "✨", "lighting": "⚡", "glow": "🌟", "glowing": "🌟",
        "shine": "✨", "shining": "✨", "bright": "🔆", "flash": "📸", "beam": "🔦",

        # Weather & Sky
        "rain": "🌧️", "raining": "🌧️", "raindrop": "💧", "raindrops": "💧",
        "storm": "⛈️", "stormy": "⛈️", "thunder": "🌩️", "lightning": "⚡",
        "cloud": "☁️", "clouds": "☁️", "cloudy": "⛅",
        "snow": "❄️", "snowing": "❄️", "ice": "🧊", "icy": "🧊", "freeze": "🥶", "freezing": "🥶",
        "winter": "❄️", "cold": "🥶", "chilly": "🧣",
        "sun": "☀️", "sunny": "☀️", "sunshine": "🌞", "sunlight": "☀️",
        "sunrise": "🌅", "sunset": "🌇", "daylight": "🌤️",
        "moon": "🌙", "moonlight": "🌕", "moonlit": "🌕",
        "star": "⭐", "stars": "✨", "starlight": "✨", "starry": "🌌",
        "sky": "🌌", "heaven": "☁️", "rainbow": "🌈", "wind": "🌬️", "breeze": "🍃",

        # Earth & Water
        "earth": "🌍", "world": "🌎", "planet": "🪐", "space": "🚀", "galaxy": "🌌", "universe": "🌌",
        "ocean": "🌊", "sea": "🌊", "wave": "🌊", "waves": "🌊",
        "river": "🏞️", "water": "💧", "lake": "🛶",
        "mountain": "🏔️", "mountains": "⛰️", "hill": "🌄",
        "flower": "🌸", "flowers": "💐", "rose": "🌹", "roses": "🌹",
        "tree": "🌳", "trees": "🌲", "forest": "🌲", "leaf": "🍃", "leaves": "🍂",
        "sand": "🏖️", "beach": "🏖️", "island": "🏝️",

        # Time & Night
        "night": "🌙", "tonight": "🌃", "midnight": "🕛", "dark": "🌑", "darkness": "🌑",
        "morning": "🌅", "day": "☀️", "today": "📅", "yesterday": "⏳", "tomorrow": "🔮",
        "time": "⏳", "clock": "⏰", "watch": "⌚", "hour": "⏳", "hours": "⏳",
        "minute": "⏱️", "seconds": "⏱️", "year": "📆", "years": "📆",
        "forever": "♾️", "never": "🚫", "always": "♾️",
        "dream": "💭", "dreams": "✨", "dreaming": "💭", "nightmare": "👹",
        "sleep": "💤", "sleeping": "😴", "awake": "👀", "wake": "⏰",

        # Body & Senses
        "eye": "👁️", "eyes": "👀", "see": "👁️", "look": "👀", "sight": "👓", "blind": "🦯",
        "hear": "👂", "listen": "🎧", "sound": "🔊", "voice": "🗣️",
        "whisper": "🤫", "scream": "😱", "shout": "📢", "call": "📞", "calling": "📱",
        "sing": "🎤", "singing": "🎶", "singer": "🎙️", "song": "🎵", "songs": "🎶",
        "music": "🎧", "beat": "🥁", "rhythm": "🎵", "guitar": "🎸", "piano": "🎹",
        "hand": "🖐️", "hands": "🤲", "hold": "🤝", "touch": "👉",
        "lips": "👄", "mouth": "👄", "face": "👤", "head": "🧠", "hair": "💇",
        "breath": "🫁", "breathe": "😮‍💨", "alive": "💓", "life": "🌱",
        "die": "💀", "death": "☠️", "dead": "🪦", "grave": "🪦", "kill": "🗡️",

        # Travel & Motion
        "run": "🏃", "running": "🏃", "walk": "🚶", "walking": "🚶",
        "drive": "🚗", "driving": "🏎️", "car": "🚘", "ride": "🏍️", "riding": "🚴",
        "train": "🚆", "plane": "✈️", "flight": "🛫", "ship": "🚢", "boat": "⛵",
        "road": "🛣️", "street": "🚦", "highway": "🛣️", "city": "🏙️", "town": "🏘️",
        "home": "🏠", "house": "🏡", "room": "🚪", "door": "🚪", "window": "🪟", "bed": "🛏️",

        # Money, Power & Royalty
        "money": "💵", "cash": "💰", "dollar": "💵", "dollars": "💸", "rich": "💎",
        "gold": "🪙", "golden": "🏆", "silver": "🥈", "diamond": "💎", "diamonds": "💎",
        "crown": "👑", "king": "👑", "queen": "👸", "prince": "🤴", "princess": "👸",
        "win": "🏆", "winner": "🥇", "champion": "🏆", "throne": "🪑",
        "fight": "🥊", "battle": "⚔️", "war": "💣", "peace": "✌️", "gun": "🔫",

        # People & Characters
        "angel": "😇", "devil": "😈", "demon": "👿", "ghost": "👻", "monster": "👾",
        "hero": "🦸", "villain": "🦹", "friend": "🤝", "friends": "🫂",
        "girl": "👧", "boy": "👦", "woman": "👩", "man": "👨", "lady": "💃",
        "mother": "👩‍👧", "mama": "👩‍👧", "father": "👨‍👦", "dad": "👨‍👦",

        # Magic, Truth & Abstract
        "magic": "🪄", "magical": "✨", "miracle": "🌟", "spell": "🧙",
        "luck": "🍀", "lucky": "🤞", "destiny": "🔮", "fate": "🕸️",
        "truth": "🔍", "true": "✅", "lie": "🤥", "lies": "🎭", "secret": "🤫",
        "promise": "🤝", "question": "❓", "why": "❓", "answer": "💡",
        "key": "🔑", "lock": "🔒", "chain": "⛓️", "chains": "⛓️",
        "drink": "🍹", "wine": "🍷", "beer": "🍺", "champagne": "🍾", "coffee": "☕",
        "smoke": "🚬", "cigarette": "🚬", "cigarettes": "🚬", "pill": "💊", "poison": "🧪",

        # Showcase vocabulary & actions
        "tell": "💬", "telling": "💬", "talk": "💬", "talking": "💬", "speak": "🗣️", "speech": "🗣️",
        "say": "💬", "said": "💬", "saying": "💬", "told": "💬",
        "name": "✍️", "sign": "✍️", "signature": "✍️", "write": "✍️", "writing": "✍️", "written": "✍️",
        "need": "🤍", "needed": "🤍", "want": "🤲", "wanted": "🤲", "wish": "✨", "wishing": "✨",
        "wait": "⌛", "waiting": "⌛", "waited": "⌛", "moment": "⏳", "patience": "⏳",
        "number": "#️⃣", "count": "🔢", "phone": "📱", "dial": "📞",
        "ball": "🏀", "ballin": "🏀", "hoop": "🏀", "game": "🎮", "play": "▶️",
        "minute": "🕐", "minutes": "🕐", "second": "⏱️", "seconds": "⏱️", "hour": "⏳",
        "faithful": "💍", "faith": "🙏", "pray": "🙏", "praying": "🙏", "believer": "🙏",
        "swear": "🤞", "sworn": "🤞", "promise": "🤞", "honest": "✨",
        "something": "✨", "nothing": "⭕", "everything": "🌌",
        "cry": "😢", "crying": "😭", "cried": "😢", "make": "🛠️",
        "heart": "🫀", "soul": "✨", "mind": "🧠", "head": "🧠",
    }

    CLEAN_PUNCT_REGEX = re.compile(r"^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$")

    def normalize_word(self, word: str) -> str:
        """Strips leading/trailing punctuation and lowers case."""
        clean = self.CLEAN_PUNCT_REGEX.sub("", word).lower()
        return clean

    def get_icon(self, word: str) -> Optional[str]:
        """Finds matched emoji/icon for word, checking direct match, plurals, and stems."""
        norm = self.normalize_word(word)
        if not norm:
            return None
        
        # 1. Direct match
        if norm in self.WORD_MAP:
            return self.WORD_MAP[norm]
        
        # 2. Plural 's' or 'es'
        if norm.endswith("s") and norm[:-1] in self.WORD_MAP:
            return self.WORD_MAP[norm[:-1]]
        if norm.endswith("es") and norm[:-2] in self.WORD_MAP:
            return self.WORD_MAP[norm[:-2]]

        # 3. Gerund 'ing' (e.g. "dancing" -> "dance", "crying" -> "cry")
        if norm.endswith("ing"):
            stem = norm[:-3]
            if stem in self.WORD_MAP:
                return self.WORD_MAP[stem]
            if stem + "e" in self.WORD_MAP:
                return self.WORD_MAP[stem + "e"]

        # 4. Past tense 'ed' (e.g. "burned" -> "burn", "loved" -> "love")
        if norm.endswith("ed"):
            stem = norm[:-2]
            if stem in self.WORD_MAP:
                return self.WORD_MAP[stem]
            if norm[:-1] in self.WORD_MAP:
                return self.WORD_MAP[norm[:-1]]

        return None

    def enrich_document(self, doc: LyricsDocument) -> LyricsDocument:
        """Injects matched icons into each LyricWord of a LyricsDocument."""
        for line in doc.lines:
            for word in line.words:
                icon = self.get_icon(word.text)
                if icon:
                    word.icon = icon
        return doc

