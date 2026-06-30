import pathlib, re

SKILL = pathlib.Path("build_context/plugins/nextseek/skills/nextseek-batch-upload/SKILL.md")

def test_skill_exists_with_frontmatter():
    txt = SKILL.read_text()
    assert txt.startswith("---"), "must have YAML front-matter"
    assert re.search(r"^name:\s*nextseek-batch-upload\s*$", txt, re.M)
    assert re.search(r"^description:\s*.+", txt, re.M)

def test_skill_forbids_upload_and_mandates_validate_and_attrs():
    txt = SKILL.read_text().lower()
    # forbidden
    assert "start/" in txt and ("forbidden" in txt or "never" in txt)
    assert "nextseek-validate-upload" in txt          # mandatory validate tool
    assert "nextseek-sampletype-attrs" in txt          # mandatory attribute fetch
    # UID rule
    assert "blank" in txt and "uid" in txt
    # format default rule
    assert "workbook" in txt and "flat" in txt
    # delivery
    assert "/data/scratch" in txt

def test_skill_has_no_eval_corpus_markers():
    # Guard against pasting the evaluation corpus into the skill.
    txt = SKILL.read_text()
    assert "pass_criteria" not in txt and "discriminator" not in txt.lower()
