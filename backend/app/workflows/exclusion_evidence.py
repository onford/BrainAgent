"""Conservative object-span checks; scope claims never become data exclusions."""
import re


def subject_numbers(quote):
    """Only parse IDs in subject lists; never count frequencies or sample sizes."""
    token = r'(?:S|sub-)?\d{1,3}'
    members = rf'{token}(?:\s*(?:[-–—]|to|至)\s*{token})?'
    lists = rf'{members}(?:\s*(?:,\s*(?:and\s+)?|;|and|、|和)\s*{members})*'
    spans = re.findall(rf'(?:subjects?|participants?|被试|参与者)\s*(?:IDs?|numbers?|编号)?\s*[:#]?\s*({lists})(?![\d+])', quote, re.I)
    spans += re.findall(rf'\b(S\d{{1,3}}(?:\s*(?:[-–—]|to|至)\s*S?\d{{1,3}})?)(?![\d+])', quote)
    found = set()
    for span in spans:
        for match in re.finditer(rf'({token})(?:\s*(?:[-–—]|to|至)\s*({token}))?', span, re.I):
            lo = int(re.sub(r'\D', '', match[1]))
            hi = int(re.sub(r'\D', '', match[2])) if match[2] else lo
            if not 0 < lo <= hi <= 999:
                raise ValueError('invalid bounded subject ID range in source')
            found.update(range(lo, hi+1))
    return found


def validate_claim(claim, entry):
    quotes = [f['quote'] for f in entry['findings'] if f['id'] in claim.finding_ids]
    span = claim.object_quote
    if not span or not any(span in q for q in quotes):
        raise ValueError('object_quote must be an exact short span of a cited finding')
    if claim.claim_type == 'unspecified':
        if claim.reported_ids:
            raise ValueError('unspecified claims must keep reported_ids empty')
        return
    if claim.claim_type == 'exclusion':
        explicit = re.search(r'\b(exclud\w*|remov\w*|discard\w*|reject\w*|omit\w*|eliminat\w*)\b|排除|剔除|舍弃', span, re.I)
        negated = re.search(r'\b(?:no|not|never|without)\b.{0,60}\b(?:exclud\w*|remov\w*|discard\w*|reject\w*|omit\w*|eliminat\w*)\b|未.{0,8}(?:排除|剔除)', span, re.I)
        if not explicit or negated:
            raise ValueError('exclusion requires an explicit, non-negated exclusion statement in object_quote; classify included/held-out subsets separately or retain unspecified with no IDs')
        if re.search(r'\b(included|selected|used|retained|training|held.out)\b|纳入|入选|保留', span, re.I):
            raise ValueError('mixed inclusion/exclusion span cannot identify excluded IDs; cite the separate explicit exclusion statement or retain unspecified with []')
    if claim.object_type == 'subject':
        numbers = subject_numbers(span)
        if any(not re.fullmatch(r'(?:S|sub-)?\d{1,3}', value) or int(re.sub(r'\D', '', value)) not in numbers for value in claim.reported_ids):
            raise ValueError('subject IDs must occur in an explicit subject list or bounded range in object_quote; do not infer IDs from counts, frequencies, other parameters or open-ended ranges; use unspecified with [] when unresolved')


def review_claim(claim, entry):
    """Unresolved secondary claims retain their proposal but cannot flag data.

    The caller still rejects unknown finding references. This projection never
    repairs labels or grants exclusion authority from a literature claim.
    """
    proposed = claim.model_dump(mode='json')
    try:
        validate_claim(claim, entry)
    except ValueError as exc:
        reason = str(exc)
        claim.claim_type = 'unspecified'
        claim.object_type = 'unspecified'
        claim.reported_ids = []
        claim.reason = '来源对象尚未确认：' + reason + '；原提案说明：' + claim.reason
        status = 'unresolved'
    else:
        reason, status = None, 'literal_scope_verified'
    return dict(entry_id=claim.entry_id, proposed=proposed, effective=claim.model_dump(mode='json'),
        status=status, reason=reason, automatic_exclusion_authorized=False)
