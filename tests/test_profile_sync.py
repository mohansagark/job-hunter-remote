"""profile_sync — builds resume + patches config from portfolio-data JSON.

The adapter reads a portfolio-data checkout (data/*.json), writes a markdown
resume, and patches config.json's candidate.{name,profile}. It must fail loudly
(non-zero exit) when a required data file is missing so a scan never runs against
a stale/empty profile.
"""
import json

import pytest

from job_hunt import profile_sync


def _write_portfolio(root):
    """Write a minimal but complete portfolio-data/data/*.json tree under root."""
    data = root / "data"
    data.mkdir(parents=True)
    (data / "profile.json").write_text(json.dumps({
        "firstName": "Mohan Sagar", "lastName": "Killamsetty",
        "headline": "AI & Frontend Software Engineer",
        "location": "Hyderabad, India",
        "bio": "Senior engineer with 9+ years building AI-powered products.",
        "email": "contact@devmohan.in",
    }))
    (data / "skills.json").write_text(json.dumps({
        "categories": [
            {"name": "Frontend", "skills": [
                {"name": "React.js", "proficiency": 95},
                {"name": "Next.js", "proficiency": 91},
            ]},
            {"name": "AI", "skills": [
                {"name": "LLM Integration", "proficiency": 90},
            ]},
        ]
    }))
    (data / "experience.json").write_text(json.dumps({
        "jobs": [
            {"company": "ServiceNow", "role": "Senior Software Engineer",
             "location": "Hyderabad", "startDate": "2025-08", "endDate": "",
             "current": True, "description": "Leading agentic AI platforms."},
            {"company": "Invesco", "role": "Senior Software Engineer",
             "location": "Hyderabad", "startDate": "2024-07", "endDate": "2025-08",
             "current": False, "description": "Led IVYGPT for 8,000+ users."},
        ]
    }))
    (data / "projects.json").write_text(json.dumps({
        "items": [
            {"shortDescription": "AI stock analysis bot",
             "technologies": ["Python", "OpenAI"], "slug": "stock-bot",
             "githubUrl": "https://github.com/mohansagark/stock-bot",
             "featured": True, "sections": [{"title": "Overview", "body": "..."}]},
            {"shortDescription": "not featured", "technologies": [], "slug": "x",
             "githubUrl": "", "featured": False, "sections": []},
        ]
    }))
    (data / "achievements.json").write_text(json.dumps({
        "items": [{"title": "Engineering Excellence Award",
                   "description": "AI R&D perf framework.", "year": "2024"}]
    }))
    return root


def _write_config(root):
    cfg = {"tinyfish_api_key": "sk-x", "candidate": {
        "name": "Your Name", "profile": "EDIT ME",
        "resume_path": "resume/YOUR_RESUME.md"}}
    (root / "config.json").write_text(json.dumps(cfg))
    return root / "config.json"


def test_sync_writes_resume_and_patches_config(tmp_path):
    src = _write_portfolio(tmp_path / "portfolio-data")
    config_path = _write_config(tmp_path)
    resume_path = tmp_path / "resume" / "YOUR_RESUME.md"

    profile_sync.sync(src=src, config_path=config_path, resume_path=resume_path)

    resume = resume_path.read_text()
    # Resume carries identity, a skill, and a recent employer.
    assert "Mohan Sagar Killamsetty" in resume
    assert "React.js" in resume
    assert "ServiceNow" in resume

    cfg = json.loads(config_path.read_text())
    assert cfg["candidate"]["name"] == "Mohan Sagar Killamsetty"
    # profile is regenerated from portfolio data, not the placeholder.
    assert cfg["candidate"]["profile"] != "EDIT ME"
    assert "AI & Frontend Software Engineer" in cfg["candidate"]["profile"]
    # unrelated candidate fields are preserved.
    assert cfg["candidate"]["resume_path"] == "resume/YOUR_RESUME.md"


def test_resume_frontloads_skills_and_recent_role(tmp_path):
    """Only the first 2500 chars feed scoring — key signal must be up front."""
    src = _write_portfolio(tmp_path / "portfolio-data")
    config_path = _write_config(tmp_path)
    resume_path = tmp_path / "resume" / "YOUR_RESUME.md"

    profile_sync.sync(src=src, config_path=config_path, resume_path=resume_path)

    head = resume_path.read_text()[:2500]
    assert "React.js" in head and "LLM Integration" in head
    assert "ServiceNow" in head


def test_missing_data_file_exits_nonzero(tmp_path):
    src = _write_portfolio(tmp_path / "portfolio-data")
    (src / "data" / "skills.json").unlink()  # simulate a missing/lost file
    config_path = _write_config(tmp_path)
    resume_path = tmp_path / "resume" / "YOUR_RESUME.md"

    with pytest.raises(SystemExit) as exc:
        profile_sync.sync(src=src, config_path=config_path, resume_path=resume_path)
    assert exc.value.code != 0


def test_missing_src_dir_exits_nonzero(tmp_path):
    config_path = _write_config(tmp_path)
    with pytest.raises(SystemExit) as exc:
        profile_sync.sync(src=tmp_path / "nope",
                          config_path=config_path,
                          resume_path=tmp_path / "resume" / "R.md")
    assert exc.value.code != 0
