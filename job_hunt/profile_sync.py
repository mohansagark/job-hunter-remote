"""Build the candidate resume + profile from a portfolio-data checkout.

Reads the structured `data/*.json` files from a `portfolio-data` repo (the source
of truth), writes a markdown resume the scanner can score against, and patches
`config.json`'s `candidate.name` / `candidate.profile`. Run at the start of every
scan so the latest skills are always used:

    python -m job_hunt.profile_sync --src ../../portfolio-data

Fails loudly (non-zero exit) if any required data file is missing, so a scan never
runs against a stale or empty profile.
"""
import argparse
import json
from pathlib import Path

# The data files this adapter depends on, relative to <src>/data/.
_REQUIRED = ("profile.json", "skills.json", "experience.json",
             "projects.json", "achievements.json")


def _fail(msg: str) -> "None":
    raise SystemExit(f"profile_sync: {msg}")


def load_portfolio(src: Path) -> dict:
    """Load and parse every required data file; exit non-zero if any is missing."""
    data_dir = Path(src) / "data"
    if not data_dir.is_dir():
        _fail(f"portfolio data dir not found: {data_dir} "
              f"(is --src pointing at a portfolio-data checkout?)")
    out: dict = {}
    for fname in _REQUIRED:
        fpath = data_dir / fname
        if not fpath.is_file():
            _fail(f"required data file missing: {fpath}")
        try:
            out[fname.removesuffix(".json")] = json.loads(fpath.read_text())
        except json.JSONDecodeError as e:
            _fail(f"could not parse {fpath}: {e}")
    return out


def _full_name(profile: dict) -> str:
    return f"{profile.get('firstName', '').strip()} {profile.get('lastName', '').strip()}".strip()


def _flat_skills(skills: dict) -> list[str]:
    names: list[str] = []
    for cat in skills.get("categories", []):
        for skill in cat.get("skills", []):
            name = skill.get("name")
            if name:
                names.append(name)
    return names


def build_profile_text(data: dict) -> str:
    """One-line-ish candidate.profile: headline + bio + flattened skills."""
    profile = data["profile"]
    headline = profile.get("headline", "").strip()
    bio = profile.get("bio", "").strip()
    skills = ", ".join(_flat_skills(data["skills"]))
    parts = [p for p in (headline, bio) if p]
    if skills:
        parts.append(f"Core skills: {skills}.")
    return " ".join(parts)


def build_resume_md(data: dict) -> str:
    """Assemble a markdown resume, front-loading the scoring signal.

    Only the first ~2500 chars feed the LLM scorer, so order is: identity →
    summary → skills → experience (recent first) → projects → achievements.
    """
    profile = data["profile"]
    name = _full_name(profile)
    lines: list[str] = [f"# {name}"]
    meta = " | ".join(p for p in (
        profile.get("headline", "").strip(),
        profile.get("location", "").strip(),
        profile.get("email", "").strip(),
    ) if p)
    if meta:
        lines += ["", meta]

    if profile.get("bio"):
        lines += ["", "## Summary", "", profile["bio"].strip()]

    # Skills grouped by category (compact — high value per char).
    cats = data["skills"].get("categories", [])
    if cats:
        lines += ["", "## Skills", ""]
        for cat in cats:
            names = ", ".join(s.get("name", "") for s in cat.get("skills", []) if s.get("name"))
            if names:
                lines.append(f"**{cat.get('name', 'Other')}:** {names}")

    jobs = data["experience"].get("jobs", [])
    if jobs:
        lines += ["", "## Experience"]
        for job in jobs:
            end = "Present" if job.get("current") or not job.get("endDate") else job["endDate"]
            span = f"{job.get('startDate', '')} – {end}".strip(" –")
            header = f"{job.get('role', '')} — {job.get('company', '')}".strip(" —")
            loc = job.get("location", "").strip()
            lines += ["", f"### {header}", f"{loc} | {span}".strip(" |")]
            if job.get("description"):
                lines += ["", job["description"].strip()]
            for h in job.get("highlights", []) or []:
                lines.append(f"- {h}")

    featured = [p for p in data["projects"].get("items", []) if p.get("featured")]
    if featured:
        lines += ["", "## Featured Projects"]
        for proj in featured:
            tech = ", ".join(proj.get("technologies", []))
            desc = proj.get("shortDescription", "").strip()
            line = f"- **{proj.get('slug', 'project')}** — {desc}"
            if tech:
                line += f" (Tech: {tech})"
            lines.append(line)

    achievements = data["achievements"].get("items", [])
    if achievements:
        lines += ["", "## Achievements"]
        for a in achievements:
            lines.append(f"- **{a.get('title', '')}** ({a.get('year', '')}) — {a.get('description', '').strip()}")

    return "\n".join(lines) + "\n"


def sync(src: Path, config_path: Path, resume_path: Path) -> None:
    """Regenerate the resume file and patch candidate.{name,profile} in config."""
    data = load_portfolio(src)

    resume_path = Path(resume_path)
    resume_path.parent.mkdir(parents=True, exist_ok=True)
    resume_path.write_text(build_resume_md(data))

    config_path = Path(config_path)
    if not config_path.is_file():
        _fail(f"config not found: {config_path}")
    cfg = json.loads(config_path.read_text())
    cand = cfg.setdefault("candidate", {})
    cand["name"] = _full_name(data["profile"])
    cand["profile"] = build_profile_text(data)
    config_path.write_text(json.dumps(cfg, indent=2) + "\n")

    print(f"profile_sync: wrote {resume_path} and patched {config_path} "
          f"for {cand['name']} ({len(_flat_skills(data['skills']))} skills)")


def main(argv: "list[str] | None" = None) -> None:
    ap = argparse.ArgumentParser(description="Sync candidate profile from portfolio-data")
    ap.add_argument("--src", required=True, help="path to a portfolio-data checkout")
    ap.add_argument("--config", default="config.json", help="config.json to patch")
    ap.add_argument("--resume", default="resume/YOUR_RESUME.md", help="resume file to write")
    args = ap.parse_args(argv)
    sync(Path(args.src), Path(args.config), Path(args.resume))


if __name__ == "__main__":
    main()
