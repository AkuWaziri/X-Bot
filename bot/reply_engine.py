import logging
import os
import re
import threading
import time
from pathlib import Path

from groq import Groq

from bot.config import GROQ_API_KEY, GROQ_MODEL, MAX_REPLY_CHARS, MIN_REPLY_CHARS
from bot.token_budget import release_tokens, reserve_tokens, settle_tokens

STYLE_EXAMPLES = """
Examples of the account's natural X reply style. These are voice references, not mandatory formats:
- Good morning fondness let's make today count
- Start now so you won’t regret later
- tbh the window keeps shrinking but yeah, now still beats tomorrow
- Chief cook officer 🔥🔥🔥
- No one does it better.
- Amazing event I wish I was there
- I tried, but could there be a problem?
- Is it possible that all my wallets have a score of zero and are all high risk? Or is there a mistake?
- Oh man, that's SICK! I luv this one...
- sorry, but we might see a 5x/10x soon after reveal
- and what basis your came at this opinion btw?
- I dont care..
- all I want is free money..
- I'm not involved in the project and will not involve as well..
- Will the agent support other languages or just English?
- I’d aim to make any post where it makes people feel good about themselves go viral.
- I’ve sent a dm javi
- Kindly check through
- Thanks
- I might know a guy, let me check my circle and hit you back bro
- Can relate
- I Made 3 figs, Lost 4 figs
- Lmaoooooo
- Damn bro! What pushed you to buy it at $133M FDV🙃🙃
- lol
- Wait I just realized you called me a giga yapper 😂
- Well, funny coincidence, but the NFT utility was revealed same time as my scheduled post sent lmao 😅 I mean it, minute to minute
- i sold and moved on
- Not just that but also putting a magnifying glass to that information.
- Funny how that works 🎯
- Dude, you guys are still censoring. Totally F'd up.
- and we are glad he buys it

IMPORTANT VOICE CALIBRATION:
A reply can be a casual fragment, a direct reaction, or an unfinished thought. Do not automatically turn every observation into a complete, polished sentence.
These examples show the intended difference in texture:
OVER-POLISHED: "Nice demo! How long does the setup actually take on average?"
MORE NATURAL: "nice demo bro! but how long does the setup take on average"
OVER-POLISHED: "AI-powered workflows sound promising, what’s the biggest win so far?"
MORE NATURAL: "AI-powered workflows... the biggest win so far"
OVER-POLISHED: "Wow, AI account managers for every customer? That’s a game changer."
MORE NATURAL: "wow, AI account managers for every customer. this is the future."
OVER-POLISHED: "Curious how they’ll handle privacy with so many AI agents."
MORE NATURAL: "i hope they handle privacy more efficiently with so many AI agents."
The point is not to copy these lines. The point is to express a direct personal reaction, opinion, hope, concern, or observation in plain conversational language. Do not inflate a reaction into marketing praise ("game changer", "revolutionary", "promising") or turn a concern into a polished engagement question ("curious how...") when a plain statement sounds more human. A reply may say what the author thinks or hopes, but must not invent personal experience, factual certainty, or unsupported claims. Preserve source meaning.

CASUAL PERSONAL-REACTION CALIBRATION:
OVER-POLISHED: "AI agent actually handling trades? That's a game-changer."
MORE NATURAL: "ngl, an AI agent handling trades on its own is intriguing."
OVER-POLISHED: "Setting risk limits yourself? Nice to keep control in your hands."
MORE NATURAL: "setting your own risk limits keeps control in your hands."
OVER-POLISHED: "NFT that pays you? Real utility is the biggest win."
MORE NATURAL: "an NFT that pays you? real utility is a big win."
Use this kind of plain, personal, slightly loose phrasing when it fits the post. "ngl" and similar openers are optional, not mandatory. Do not copy these examples unless the source post is actually about the same details. Prefer a genuine reaction ("this part is intriguing", "i like that...", "i hope...", "that keeps control...") over generic praise or polished marketing language. Keep grammar natural; casual does not mean deliberately broken.
"""

PUBLIC_HUMAN_REPLY_PATTERNS = """
HUMAN REPLY DNA
These are voice patterns and examples, not a phrase bank to copy mechanically.
Use them only when the actual post supports the same reaction.

EARLY / ALPHA:
- feels earlier than people realize
- still early enough to matter
- the kind of thing you wish you found sooner
- early signals looking good
- getting early vibes from this
- this might be one of those before everyone notices moments
- catching this before the crowd feels nice
- the timing on this feels interesting
- feels like an early conviction play
- worth paying attention before it gets crowded
- this feels early
- low noise, high signal
- this has alpha written all over it
- something's cooking here
- not loud, but very intentional
- feels like one of those bookmark and come back plays
- the kind of thing you notice before CT catches on
- this is flying under the radar for now
- ive seen enough to pay attention

BUILDERS / EXECUTION:
- builders keep building
- the work is showing
- execution over everything
- shipping season
- real progress is hard to fake
- you can tell they're actually putting in the work
- steady building always wins
- the receipts are there
- the product keeps speaking for itself
- this is what consistency looks like
- good teams ship
- the execution keeps stacking up
- building through the noise
- the difference is in the delivery
- actions > announcements
- no hype just real builders
- you can tell this was built, not rushed
- real builders, real product
- this didnt come out of a hype sprint
- the execution says a lot
- this feels engineered, not marketed
- consistency like this doesnt happen by accident
- builder mindset > trend chasing

PRODUCT / QUALITY:
- clean product
- clean work
- the UX looks solid
- someone actually thought this through
- the details matter and it shows
- this feels polished
- good product energy
- the experience feels intentional
- a lot of thought behind this
- simple done right
- the product direction makes sense
- looks user-first
- this feels practical
- quality over noise
- smooth experience from what ive seen
- thoughtful design all over this
- product-first energy
- simple, but it actually works
- the approach alone stands out

UNDER THE RADAR:
- still underrated
- surprised more people arent talking about this
- quietly making moves
- flying lower than it should
- somehow still under the radar
- this deserves more attention
- not enough eyes on this yet
- hidden in plain sight
- one of those quiet winners
- easy to overlook, hard to ignore
- people will catch on eventually
- watching this closely
- this feels like something people will notice later
- not many people talking about this yet, which is interesting

CONVICTION / WATCHING:
- keeping this on my radar
- watching this one
- following this closely
- interested to see where this goes
- not ignoring this
- worth tracking
- definitely monitoring this
- curious to see the next update
- this earned a follow
- looking forward to whats next
- paying attention here
- im tuned in
- worth a closer look
- gonna look into this
- bookmarking this mentally

REWARDS / COMMUNITY:
- love seeing contributors recognized
- community-first done right
- participation actually matters here
- rewarding people properly never gets old
- this makes contribution feel worthwhile
- good incentives create good communities
- this feels fair
- the community angle is strong
- recognition matters
- nice to see users getting value back
- finally a reward system that actually rewards the people putting in the work
- this actually respects contributors
- rewarding participation done right
- feels fair, which is rare
- this is how you build loyal users
- incentives finally make sense here
- work -> value -> ownership, simple

ECOSYSTEM / LONG TERM:
- playing the long game
- thinking beyond the next cycle
- long-term mindset
- building something that can last
- this feels sustainable
- strong foundations matter
- looks built for longevity
- thinking bigger than short-term attention
- the ecosystem approach makes sense
- the pieces fit together
- this looks designed to grow
- future-proof mindset
- this is what real ecosystem building looks like
- you can feel the long-term thinking
- built for users, not just charts
- everything feels connected, not forced
- this is how you grow something real
- looks designed to last
- foundations > fireworks
- this feels like it scales naturally

REACTION / EMOTION:
- okay this caught my eye
- cant lie, this looks good
- well thats impressive
- love to see it
- this is cool
- pretty neat actually
- not bad at all
- thats a nice update
- solid work
- respect
- im into this
- lets go
- very nice
- quietly impressive
- this hits different
- yeah, you can feel the difference here
- thats what stood out to me too
- been watching this for a bit now
- glad someone else noticed this
- thats the part people are missing

BIG ANNOUNCEMENTS:
- huge step forward
- this is a meaningful update
- thats a strong move
- big milestone
- moving in the right direction
- thats how momentum is built
- one update at a time
- the progress is adding up
- good direction
- this opens up a lot of possibilities
- nice to see this rolling out
- looking forward to seeing the impact
- the work is showing

PARTNERSHIPS / COLLABORATIONS:
- this partnership makes sense
- good fit
- smart collaboration
- interesting combination
- love seeing teams work together
- strong alignment here
- this could be powerful
- nice pairing
- this feels natural
- curious to see what comes from this
- solid move from both sides
- looking forward to seeing the results

LOW-NOISE / ANTI-HYPE:
- no hype, just progress and visible execution
- refreshing to see a project focused on building instead of marketing
- feels grounded and practical, which is rare in this space
- less talking, more shipping thats always a good sign
- this is surprisingly sane for crypto
- no gimmicks detected
- calm execution > loud narratives
- no flashy promises, just shipping
- finally, less talk more build
- this is how it should be done
- feels grounded
- the work speaks for itself

DIFFERENT / DISTINCTIVE:
- this genuinely feels different from the usual crypto copy-paste
- not your average web3 launch
- this approach alone separates it from most things launching lately
- hard to explain, but this definitely hits different already
- everything about this feels more intentional than typical crypto plays
- this isnt copy-paste web3
- the approach alone stands out
- hard to ignore this one
- this doesnt feel like the usual playbook
- something about this feels solid
- not many projects move like this
- this has its own lane

SHORT HUMAN FORMS:
Humans often type compressed reactions rather than complete sentences:
- tbh
- fr
- lol
- lmao
- ngl
- idk
- imo
- rn
- btw
- yep
- nah
- yep, exactly
- fair enough
- makes sense
- cant lie
- not wrong
- thats fair
- good shout
- say less
- lowkey
- highkey
- wait what
- no way
- thats wild
- damn
- sheesh
- bruh
- real talk
- i hear you
- can relate
- same here
- honestly yeah
- yeah, pretty much
These are building blocks, not automatic replies. A standalone short form is valid only when it fits the actual post and still satisfies the 20-100 character rule.

TWITTER / X NATIVE BEHAVIOR:
- React to one phrase, number, screenshot detail, announcement detail, or punchline.
- A quote-tweet-like observation can work, but do not restate the whole post.
- Reply to the person, not to an imaginary audience.
- Use lowercase naturally, especially for casual reactions.
- A tiny follow-up can work when the post leaves a real detail open.
- People often reply with "real", "fair", "nah", "lol", "wait", or a half-sentence.
- Crypto CT often uses compressed language, but do not turn every reply into crypto slang.
- Mild teasing is natural when the post gives you something to tease.
- Agreement should contain a reason or specific detail when possible.
- Skepticism should target the claim, not the person.
- Do not manufacture hype because a post mentions a token, launch, funding, points, or partnership.

REDDIT-LIKE BEHAVIOR:
- Context-first replies are common.
- Add one useful detail rather than writing a full essay.
- "This happened to me too" style resonance works when genuinely supported.
- Dry humor and understatement can be more natural than praise.
- Challenge a claim calmly when the post invites discussion.
- Correct one concrete detail when you actually know it from the post/context.
- Ask for clarification only when the missing detail genuinely matters.
- Avoid sounding like a brand account or promotional commenter.
- Do not use Reddit-style long explanations when a short reaction fits.

TWITCH / LIVE-CHAT-LIKE BEHAVIOR:
- Fast reactions to something that just happened: "nahhh", "lmaooo", "wait", "bro", "no shot".
- React to the exact moment, joke, fail, win, reveal, or unexpected turn.
- Short bursts and fragments are natural.
- Chat language can be looser and more immediate than normal X replies.
- Do not force streamer slang when the source post is not playful.
- Do not turn every reply into hype.

DISCORD / COMMUNITY CHAT BEHAVIOR:
- Casual acknowledgement can be enough.
- Use "fair", "makes sense", "good catch", "same", or "that checks out" when genuinely appropriate.
- People often respond to one practical detail rather than summarizing the whole message.
- Helpful replies can be short and direct.
- Avoid corporate wording.

HUMAN IMPERFECTION:
- Lowercase starts are allowed.
- Missing apostrophes are allowed: dont, cant, ive, whats.
- Loose punctuation is allowed.
- Short fragments are allowed.
- Repeated letters can occasionally signal emotion: lmaooo, nahhh.
- One emoji can work when the emotion supports it.
- Do not add typos or slang artificially.
- Do not make every reply lowercase.
- Do not make every reply contain an emoji.
- Do not make every reply use crypto vocabulary.

IMPORTANT:
The examples above are not a list to rotate through. Never select a phrase just because it matches a category label.
First identify the post type, emotional tone, specific trigger/detail, and what a normal person would naturally notice.
Then choose a response lane.
If a category does not fit the post, ignore it completely.
"""

def _load_reply_dna_reference() -> str:
    """Load the behavioral DNA guidance, excluding raw examples that could become canned replies."""
    dna_path = Path(__file__).resolve().parents[1] / "docs" / "reply_dna_samples.md"
    try:
        document = dna_path.read_text(encoding="utf-8")
    except OSError:
        # Keep the generator usable if documentation is omitted from a packaged runtime.
        return (
            "Human does not mean polished, positive, insightful, or always polite. "
            "Match the moment. React to a specific detail; allow blunt reactions, jokes, "
            "skepticism, disagreement, fragments, and uneven tone when appropriate. "
            "Do not force praise, questions, slang, emojis, or three identical sentence shapes. "
            "Never invent facts or personal experience. Critique claims and behavior, not identity."
        )

    section_start = document.find("## How the generator should apply this DNA")
    if section_start < 0:
        return (
            "Match the moment and react to a specific detail. Prefer natural over polished. "
            "Do not force praise, questions, slang, or emojis. Never invent facts or personal "
            "experience; critique claims and behavior, not identity."
        )
    # This section contains application rules, not the raw sample phrase bank.
    return document[section_start:].strip()


# Groq is shared by /project and the scheduled-feed worker in this process.
# Serialize calls and leave room under TPM limits instead of bursting requests.
_GROQ_REQUEST_LOCK = threading.Lock()
_GROQ_MIN_INTERVAL_SECONDS = 6.0
_GROQ_LAST_REQUEST_AT = 0.0


def _create_groq_completion(client, **kwargs):
    global _GROQ_LAST_REQUEST_AT
    with _GROQ_REQUEST_LOCK:
        min_interval = max(0.0, float(os.getenv("GROQ_MIN_INTERVAL_SECONDS", str(_GROQ_MIN_INTERVAL_SECONDS))))
        wait_for = min_interval - (time.monotonic() - _GROQ_LAST_REQUEST_AT)
        if wait_for > 0:
            time.sleep(wait_for)
        rate_limit_retries = max(0, int(os.getenv("GROQ_RATE_LIMIT_RETRIES", "3")))
        for retry_number in range(rate_limit_retries + 1):
            try:
                response = client.chat.completions.create(**kwargs)
                _GROQ_LAST_REQUEST_AT = time.monotonic()
                return response
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if (status != 429 and "429" not in str(exc)) or retry_number >= rate_limit_retries:
                    _GROQ_LAST_REQUEST_AT = time.monotonic()
                    raise
                headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
                retry_after = headers.get("retry-after") or headers.get("Retry-After")
                fallback_delay = min(20.0 * (2 ** retry_number), 60.0)
                try:
                    delay = min(max(float(retry_after), 1.0), 120.0) if retry_after else fallback_delay
                except (TypeError, ValueError):
                    delay = fallback_delay
                logging.warning(
                    "Groq rate limit reached; retrying | attempt=%s | wait_seconds=%s",
                    retry_number + 1,
                    delay,
                )
                time.sleep(delay)
                _GROQ_LAST_REQUEST_AT = time.monotonic()
        raise RuntimeError("Groq request exhausted rate-limit retries")


REPLY_DNA_REFERENCE = _load_reply_dna_reference()
# Keep the large phrase bank out of the live prompt. It is retained above as
# documentation/reference material, but feeding every sample to the model
# encourages repeated, canned replies instead of post-specific reactions.
COMBINED_REPLY_DNA = REPLY_DNA_REFERENCE


SYSTEM_PROMPT = """Write exactly three distinct, natural X replies to the supplied post.
React to specific details; preserve meaning; never invent facts or personal experience.
Use casual, human wording. Avoid generic praise, marketing language, canned phrases, and em dashes.
Prefer short, specific statements or fragments. Do not ask questions or use question marks.
Avoid the phrases: actually, feels like, feels off, this or that.
Output exactly these three lines, with no intro, bullets, quotes, or extra text:
R1: [reply]
R2: [reply]
R3: [reply]
Each reply must meet the requested character range and be distinct."""


def _clean_reply(reply: str) -> str:
    # X replies should read like normal human typing. Never allow em dashes
    # through, even if the model ignores the instruction in the prompt.
    reply = re.sub(r"\s*[—]\s*", ", ", reply.strip())
    reply = re.sub(r"\s+", " ", reply)
    reply = re.sub(r"^(?:R[123]\s*:\s*|[-*•]\s*|\d+[.)]\s*)", "", reply, flags=re.IGNORECASE)
    return reply.strip('"').strip()


GENERIC_REPLIES = {
    "great post",
    "interesting",
    "absolutely",
    "well said",
    "this",
    "exactly",
    "love this",
    "great point",
    "good point",
    "so true",
    "couldn't agree more",
    "could not agree more",
}


def _valid_reply(reply: str) -> bool:
    normalized = re.sub(r"[.!?]+$", "", reply.strip().lower())
    if not MIN_REPLY_CHARS <= len(reply) <= MAX_REPLY_CHARS:
        return False
    if normalized in GENERIC_REPLIES:
        return False
    if "—" in reply:
        return False
    # Questions are allowed sparingly, but the question mark must close the reply.
    if "?" in reply and not reply.rstrip().endswith("?"):
        return False
    # Block recurring filler and vague contrast patterns the user dislikes.
    if re.search(r"\bactually\b|\bfeels\s+like\b|\bfeels\s+off\b|\bthis\s+or\s+that\b", reply, re.IGNORECASE):
        return False
    return True


def _parse_reply_candidates(raw: str) -> list[str]:
    """Extract reply candidates without silently discarding style failures."""
    if not raw or raw.upper().strip() == "NO_REPLY":
        return []

    text = raw.replace("\\r\n", "\n").replace("\n", "\n")
    text = re.sub(r"```(?:text|markdown)?", "", text, flags=re.IGNORECASE).replace("```", "").strip()
    tagged_matches = list(re.finditer(r"(?<!\w)(R[123])\s*:\s*", text, flags=re.IGNORECASE))
    candidates: list[str] = []
    if len(tagged_matches) >= 3:
        tagged = {}
        for index, match in enumerate(tagged_matches):
            label = match.group(1).upper()
            if label in tagged:
                continue
            end = tagged_matches[index + 1].start() if index + 1 < len(tagged_matches) else len(text)
            tagged[label] = text[match.end():end].strip()
        if all(label in tagged for label in ("R1", "R2", "R3")):
            candidates = [tagged["R1"], tagged["R2"], tagged["R3"]]

    if len(candidates) != 3:
        numbered_matches = list(re.finditer(r"(?im)^\s*(?:reply\s*)?([123])\s*[:.)-]\s*", text))
        if len(numbered_matches) >= 3:
            numbered = {}
            for index, match in enumerate(numbered_matches):
                label = match.group(1)
                if label in numbered:
                    continue
                end = numbered_matches[index + 1].start() if index + 1 < len(numbered_matches) else len(text)
                numbered[label] = text[match.end():end].strip()
            if all(label in numbered for label in ("1", "2", "3")):
                candidates = [numbered["1"], numbered["2"], numbered["3"]]

    if len(candidates) != 3:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) == 3:
            candidates = lines

    return [_clean_reply(candidate) for candidate in candidates]


def _reply_validation_errors(replies: list[str]) -> list[str]:
    """Return actionable reasons a generated reply set failed validation."""
    errors = []
    if len(replies) != 3:
        errors.append(f"expected exactly 3 replies, received {len(replies)}")
    for index, reply in enumerate(replies, start=1):
        issues = []
        if not MIN_REPLY_CHARS <= len(reply) <= MAX_REPLY_CHARS:
            issues.append(f"must be {MIN_REPLY_CHARS}-{MAX_REPLY_CHARS} characters (currently {len(reply)})")
        if re.sub(r"[.!?]+$", "", reply.strip().lower()) in GENERIC_REPLIES:
            issues.append("too generic; make it specific to the post")
        if "—" in reply:
            issues.append("contains a forbidden em dash")
        if "?" in reply and not reply.rstrip().endswith("?"):
            issues.append("question mark must be the final character")
        if re.search(r"\bactually\b|\bfeels\s+like\b|\bfeels\s+off\b|\bthis\s+or\s+that\b", reply, re.IGNORECASE):
            issues.append('contains a prohibited phrase ("actually", "feels like", "feels off", or "this or that")')
        if issues:
            errors.append(f"R{index}: " + "; ".join(issues))
    if len(set(replies)) != len(replies):
        errors.append("all three replies must be distinct")
    if sum("?" in reply for reply in replies) > 1:
        errors.append("at most one reply may be a question")
    return errors


def _parse_replies(raw: str) -> list[str]:
    """Extract three model replies and retain only individually valid options."""
    replies = []
    for cleaned in _parse_reply_candidates(raw):
        if cleaned.upper() != "NO_REPLY" and _valid_reply(cleaned) and cleaned not in replies:
            replies.append(cleaned)
    return replies

def generate_replies(
    post_text: str,
    *,
    request_timeout: float | None = None,
    max_retries: int | None = None,
    usage_class: str = "comments",
) -> list[str] | None:
    """Generate three distinct human-style reply suggestions, or None."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    client_options = {"api_key": GROQ_API_KEY}
    if request_timeout is not None:
        client_options["timeout"] = request_timeout
    if max_retries is not None:
        client_options["max_retries"] = max_retries
    client_options["max_retries"] = 0 if max_retries is None else max_retries
    client = Groq(**client_options)

    replies: list[str] = []
    raw = ""
    validation_errors: list[str] = []
    validation_attempts = max(1, min(2, int(os.getenv("GROQ_VALIDATION_ATTEMPTS", "2"))))
    for attempt in range(validation_attempts):
        user_prompt = f"""POST TO REPLY TO:\n{post_text[:800]}\n\nWrite three believable, casual X replies. React to specific details in this post; do not summarize it or invent facts. Use short, natural statements or fragments, with varied wording and sentence shapes. Do not ask questions or use question marks. Avoid generic praise, marketing language, canned phrases, "actually", "feels like", "feels off", "this or that", and em dashes. Return exactly three labeled lines and nothing else: R1: [reply], R2: [reply], R3: [reply]. Each reply must be {MIN_REPLY_CHARS}-{MAX_REPLY_CHARS} characters and distinct."""
        if attempt:
            feedback = "\n".join(f"- {error}" for error in validation_errors) or "- Follow the required three-line format exactly."
            user_prompt += (
                "\n\nYour previous attempt failed these exact checks:\n"
                f"{feedback}\n"
                "Regenerate all three replies and correct every listed issue. Keep the same post-specific, natural voice; "
                "do not make the replies generic just to pass validation. Use exactly three lines and no extra text:\n"
                "R1: [reply]\nR2: [reply]\nR3: [reply]"
            )
        reservation_id = reserve_tokens(usage_class)
        try:
            completion = _create_groq_completion(
                client,
                model=GROQ_MODEL,
                temperature=0.7,
                max_completion_tokens=220,
                reasoning_effort="low",
                include_reasoning=False,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            try:
                release_tokens(reservation_id)
            except Exception:
                logging.exception("Groq token reservation release failed")
            raise RuntimeError(f"Groq request failed: {exc}") from exc

        usage = getattr(completion, "usage", None)
        actual_tokens = getattr(usage, "total_tokens", None) if usage else None
        if actual_tokens is None:
            actual_tokens = 3000
            logging.warning("Groq response omitted usage metadata; settling conservative estimate")
        try:
            settle_tokens(reservation_id, int(actual_tokens))
        except Exception:
            # Do not discard successfully generated suggestions because usage
            # accounting failed; the reservation remains visible for recovery.
            logging.exception("Groq token usage settlement failed | reservation=%s", reservation_id)
        logging.info(
            "GROQ RESPONSE USAGE | class=%s | prompt_tokens=%s | completion_tokens=%s | total_tokens=%s",
            usage_class,
            getattr(usage, "prompt_tokens", "unknown") if usage else "unknown",
            getattr(usage, "completion_tokens", "unknown") if usage else "unknown",
            actual_tokens,
        )

        raw = (completion.choices[0].message.content or "").strip()
        replies = _parse_reply_candidates(raw)
        validation_errors = _reply_validation_errors(replies)
        if validation_errors:
            logging.warning(
                "Groq reply validation failed | attempt=%s | finish_reason=%s | errors=%s | reply_lengths=%s | raw_sample=%r",
                attempt + 1,
                getattr(completion.choices[0], "finish_reason", None),
                validation_errors,
                [len(reply) for reply in replies],
                raw[:500],
            )
        else:
            break

    if validation_errors:
        raise RuntimeError(
            f"Groq returned replies that failed style validation after {validation_attempts} attempt(s): "
            + "; ".join(validation_errors)
        )

    # Final hard guard. This catches anything introduced by future prompt/model
    # changes before a suggestion is stored or sent to Telegram.
    if any("—" in reply for reply in replies):
        raise RuntimeError("Groq returned an em dash in a reply")
    if sum("?" in reply for reply in replies) > 1:
        raise RuntimeError("Groq returned more than one question across the three replies")
    if any("?" in reply and not reply.rstrip().endswith("?") for reply in replies):
        raise RuntimeError("Groq returned a question mark before the end of a reply")

    return replies


def validate_replies(replies: list[str] | None) -> bool:
    if not replies or len(replies) != 3:
        return False
    if not all(_valid_reply(reply) for reply in replies) or len(set(replies)) != 3:
        return False
    return sum("?" in reply for reply in replies) <= 1


def validate_reply(reply: str | None) -> bool:
    if reply is None:
        return False
    return _valid_reply(reply)
