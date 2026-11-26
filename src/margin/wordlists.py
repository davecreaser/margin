"""Hand-made word lists for the habits report and house style (spec 0007). English only.

Spelling pairs leave out words that are correct both ways in one variety (practice and
practise, licence and license, program and programme, tire and tyre, curb and kerb, check and
cheque, story and storey, judgement, ageing, draught, meter): guessing there would report the
author's correct choice.
"""

# Words a repeated phrase needs more than: a phrase of only these is never reported.
FUNCTION_WORDS = frozenset(
    """
    a an the and or but nor so yet for of to in on at by from with without into onto upon
    over under about above below after before between through during against among around
    across along behind beside beyond near off out up down than then there here this that
    these those it its it's is are was were be been being am do does did done have has had
    having will would shall should can could may might must not no yes i me my mine we us our
    you your he him his she her hers they them their what which who whom whose when where why
    how all any some each every both either neither one ones other another such own same so
    very too just as if though while because until unless since once again ever never also
    only even still back now well like more most much many few less least said says say
    went go goes going come came get got make made let us just quite rather oh mr mrs miss ms
    don't didn't wasn't weren't isn't aren't couldn't wouldn't shouldn't can't won't i'm i'd
    i'll he'd she'd they'd we'd you'd that's there's what's it'd ought
    """.split()
    # Nouns and verbs that English uses as grammar: "in front of", "the fact that", "at any
    # rate", "he knew that". A phrase made only of these is idiom, not the author's habit.
    + """
    front end part order fact rate course bit sort kind way time times thing things lot side
    top middle rest number deal case point place matter moment instance least
    know knew known think thought seem seems seemed feel felt look looked see saw seen take
    took give gave tell told ask asked began begin want wanted put day days
    """.split()
    # Quantities, money and time: "half an hour", "shillings a week", "five pound note".
    + """
    two three four five six seven eight nine ten eleven twelve twenty thirty forty fifty sixty
    seventy eighty ninety hundred hundreds thousand thousands million half quarter first second
    third last next few several dozen pound pounds shilling shillings pence penny crown crowns
    guinea guineas twopence threepence fourpence sixpence halfpenny ha'penny farthing cent per
    note notes week weeks year years hour hours minute minutes month months
    mile miles yard yards foot feet inch inches morning evening night afternoon o'clock
    great hand room
    """.split()
)

# A phrase doesn't end on these: "a quarter of an" is part of "a quarter of an hour".
DANGLING = frozenset(
    "the a an of to in on at by for with from and or but that as into upon than per <their>".split()
)

PRONOUN_FOLD = {
    **dict.fromkeys(["his", "her", "their", "its", "my", "your", "our"], "<their>"),
    **dict.fromkeys(["he", "she", "they", "i", "we", "you"], "<they>"),
    **dict.fromkeys(["him", "them", "me", "us"], "<them>"),
    **dict.fromkeys(["himself", "herself", "themselves", "myself", "yourself"], "<themself>"),
}

# Words before a noun: "a felt hat", "the very man", "a curt nod" are not habits.
DETERMINERS = frozenset(
    "a an the this that these those his her their its my your our no one every each some any "
    "another either neither whose which what such".split()
)
SUBJECTS = frozenset("i you he she it we they who".split())
AUXILIARIES = frozenset(
    "would could should might may can will shall must did didn't don't doesn't to "
    "wouldn't couldn't shouldn't won't can't".split()
)

# Stock gestures with one verb: past and -ing forms count, base and -s forms only after a
# subject or an auxiliary ("she nods", "would smile"), never after a determiner (nouns).
GESTURE_VERBS = {
    "shrugged": ["shrug", "shrugs", "shrugged", "shrugging"],
    "nodded": ["nod", "nods", "nodded", "nodding"],
    "sighed": ["sigh", "sighs", "sighed", "sighing"],
    "smiled": ["smile", "smiles", "smiled", "smiling"],
    "grinned": ["grin", "grins", "grinned", "grinning"],
    "frowned": ["frown", "frowns", "frowned", "frowning"],
    "winced": ["wince", "winces", "winced", "wincing"],
}
POSS = r"(?:his|her|their|my|your|its|our|the)"
GESTURE_PHRASES = {
    "rolled eyes": rf"\b(?:roll|rolls|rolled|rolling) {POSS} eyes\b",
    "raised an eyebrow": r"\b(?:raise|raises|raised|raising) (?:an|a|one|his|her|their|my|your|both) eyebrows?\b",
    "bit lip": rf"\b(?:bite|bites|bit|biting|bitten) {POSS} (?:lower |bottom )?lips?\b",
    "jaw tightened": r"\bjaws? (?:tightened|tightening|tightens|tighten|clenched|clenching|clenches|clench)\b",
    "ran a hand through hair": rf"\b(?:run|runs|ran|running) (?:a|his|her|their|my|your|both) hands? through {POSS} hair\b",
    "breath didn't know … holding": r"\blet (?:out )?(?:a|the) breath (?:[\w’']+ ){0,4}?(?:didn['’]t|did not|hadn['’]t|had not) (?:even )?(?:know|realised|realized) (?:[\w’']+ ){0,4}?holding\b",
    "heart pounded": r"\bhearts? (?:pounded|pounding|pounds|pound|raced|racing|races|race)\b",
}

# Filter verbs: every form, except after a determiner ("a felt hat", "the saw", "his watch").
FILTER_VERBS = {
    "felt": ["feel", "feels", "felt", "feeling"],
    "saw": ["see", "sees", "saw", "seen", "seeing"],
    "heard": ["hear", "hears", "heard", "hearing"],
    "noticed": ["notice", "notices", "noticed", "noticing"],
    "realised": ["realise", "realises", "realised", "realising"]
    + ["realize", "realizes", "realized", "realizing"],
    "seemed": ["seem", "seems", "seemed", "seeming"],
    "watched": ["watch", "watches", "watched", "watching"],
    "wondered": ["wonder", "wonders", "wondered", "wondering"],
}

CRUTCH_WORDS = ["just", "really", "very", "suddenly", "somehow", "actually"]
# Words after which a base verb form still reads as a verb: "let them see", "I never notice".
VERB_LEADS = frozenset(
    "him her them me us not never always often still also only even really just and or then "
    "could".split()
)

# The words before which a crutch word is an adjective: "a just man", "the very man". "Very"
# after "a" is the adverb ("a very friendly style"); "just" after "that" or "which" is too.
CRUTCH_AS_ADJECTIVE = {
    "just": frozenset("a an the his her their its my your our every no one such".split()),
    "very": frozenset("the this that these those his her their its my your our".split()),
}

# "as soon as" is grammar, not a simile.
AS_AS_NOT = frozenset(
    "soon well far much long many few little though if yet usual ever good such to it the a "
    "an often quickly".split()
)
LIKE_A_NOT = frozenset(
    "i you we they he she would should could might do does did don't doesn't didn't to "
    "i'd you'd we'd they'd he'd she'd".split()
)

# "-ing" words that open a sentence without being a participle.
ING_NOT_PARTICIPLE = frozenset(
    "nothing something anything everything morning evening during king thing things ring "
    "spring string sing bring cling swing sting wing ceiling darling stocking pudding "
    "building wedding meeting notwithstanding according including concerning regarding "
    "pending".split()
)


MONTHS = """january february march april may june july august september october november
    december jan feb mar apr jun jul aug sep sept oct nov dec""".split()


# --- Spelling ------------------------------------------------------------------------------


def _forms(stem_gb: str, stem_us: str, endings: list[str]) -> list[tuple[str, str]]:
    return [(stem_gb + e, stem_us + e) for e in endings]


def _spelling_pairs() -> list[tuple[str, str, str]]:
    """(british, american, group). Group "ize" is the -ise/-ize set, which british-oxford
    spells the American way."""
    pairs: list[tuple[str, str, str]] = []
    our = """colour honour favour flavour harbour labour neighbour rumour humour vapour behaviour
        savour splendour parlour odour armour clamour endeavour fervour valour vigour rigour
        tumour candour ardour""".split()
    for w in our:
        stem_gb, stem_us = w, w[:-2] + "r"
        for gb, us in _forms(stem_gb, stem_us, ["", "s", "ed", "ing", "ful", "less", "able"]):
            pairs.append((gb, us, "our"))
    pairs += [(a, b, "our") for a, b in [("favourite", "favorite"), ("favourites", "favorites"),
                                          ("neighbourhood", "neighborhood"), ("neighbourly", "neighborly"),
                                          ("colourful", "colorful"), ("honourable", "honorable"),
                                          ("favourably", "favorably"), ("labourer", "laborer"),
                                          ("labourers", "laborers"), ("behaviours", "behaviors")]]  # fmt: skip
    re_er = """centre theatre fibre litre lustre sombre spectre calibre sabre meagre manoeuvre
        louvre""".split()
    for w in re_er:
        us = "maneuver" if w == "manoeuvre" else w[:-2] + "er"
        for e in ["", "s", "d"]:
            gb = w + e
            pairs.append((gb, us + ("ed" if e == "d" else e), "re"))
    ise = """realis recognis organis apologis criticis emphasis memoris sympathis summaris
        prioritis utilis agonis authoris civilis idolis scrutinis tantalis terroris mesmeris
        characteris specialis finalis minimis maximis visualis vocalis hypnotis patronis
        fantasis ostracis jeopardis legitimis symbolis harmonis colonis stabilis standardis
        neutralis familiaris sterilis moralis romanticis theoris trivialis vandalis
        immortalis antagonis capitalis categoris dramatis energis fertilis glamoris
        italicis jeopardis mobilis modernis monopolis normalis optimis penalis
        personalis popularis publicis rationalis revolutionis sensitis sanitis
        socialis subsidis synchronis tranquillis""".split()
    for stem in ise:
        us_stem = stem[:-1] + "z"
        for e in ["e", "es", "ed", "ing", "ation", "ations", "er", "ers"]:
            pairs.append((stem + e, us_stem + e, "ize"))
    for stem in ["analy", "paraly", "cataly"]:
        for e in ["se", "ses", "sed", "sing"]:
            pairs.append((stem + e, stem + e.replace("s", "z", 1), "yse"))
    ll = """travel cancel label model quarrel marvel fuel level signal counsel dial duel equal
        grovel channel tunnel shovel swivel total panel pencil rival snivel unravel revel
        jewel yodel""".split()
    for w in ll:
        for e in ["led", "ling", "ler", "lers"]:
            pairs.append((w + e, w + e[1:], "ll"))
    pairs += [(a, b, "other") for a, b in [
        ("marvellous", "marvelous"), ("jewellery", "jewelry"), ("woollen", "woolen"),
        ("grey", "gray"), ("greyer", "grayer"), ("greying", "graying"), ("greyish", "grayish"),
        ("aluminium", "aluminum"), ("plough", "plow"), ("ploughed", "plowed"),
        ("ploughing", "plowing"), ("ploughs", "plows"), ("mould", "mold"), ("mouldy", "moldy"),
        ("mouldering", "moldering"), ("smoulder", "smolder"), ("smouldered", "smoldered"),
        ("smouldering", "smoldering"), ("moult", "molt"), ("sceptic", "skeptic"),
        ("sceptical", "skeptical"), ("scepticism", "skepticism"), ("defence", "defense"),
        ("offence", "offense"), ("pretence", "pretense"), ("catalogue", "catalog"),
        ("analogue", "analog"), ("pyjamas", "pajamas"), ("aeroplane", "airplane"),
        ("aeroplanes", "airplanes"), ("foetus", "fetus"), ("anaesthetic", "anesthetic"),
        ("encyclopaedia", "encyclopedia"), ("enrol", "enroll"), ("enrols", "enrolls"),
        ("enrolment", "enrollment"), ("fulfil", "fulfill"), ("fulfils", "fulfills"),
        ("fulfilment", "fulfillment"), ("skilful", "skillful"), ("skilfully", "skillfully"),
        ("wilful", "willful"), ("wilfully", "willfully"), ("instalment", "installment"),
        ("distil", "distill"), ("cosy", "cozy"), ("cosier", "cozier"), ("moustache", "mustache"),
        ("moustaches", "mustaches"), ("sulphur", "sulfur"), ("axe", "ax"),
        ("mediaeval", "medieval"), ("oesophagus", "esophagus"), ("paediatric", "pediatric"),
        ("manoeuvring", "maneuvering"), ("whilst", "while"), ("amongst", "among"),
    ]]  # fmt: skip
    # Words correct in both varieties drop out.
    both = {"while", "among", "medieval"}
    return [(gb, us, g) for gb, us, g in pairs if gb != us and us not in both and gb not in both]


SPELLING_PAIRS = _spelling_pairs()
