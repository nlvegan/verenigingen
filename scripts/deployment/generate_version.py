#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Version Generator
Generates semantic version based on git history and commit messages
"""

import subprocess
import re
from datetime import datetime
from pathlib import Path


class VersionGenerator:
    """Generate semantic version for deployment"""
    
    def __init__(self):
        self.app_path = Path(__file__).parent.parent.parent
        
    def get_current_version(self):
        """Get current version from git tags"""
        try:
            # Get latest tag
            result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            
            if result.returncode == 0:
                tag = result.stdout.strip()
                # Extract version from tag (v1.2.3 -> 1.2.3)
                version_match = re.match(r'v?(\d+)\.(\d+)\.(\d+)', tag)
                if version_match:
                    return tuple(map(int, version_match.groups()))
                    
        except Exception:
            pass
            
        # Default to 0.0.0 if no tags
        return (0, 0, 0)
        
    def analyze_commits_since_tag(self):
        """Analyze commits since last tag to determine version bump"""
        try:
            # First get the last tag safely
            tag_result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            
            # Get commits since last tag
            if tag_result.returncode == 0:
                last_tag = tag_result.stdout.strip()
                result = subprocess.run(
                    ["git", "log", "--pretty=format:%s", f"HEAD...{last_tag}"],
                    capture_output=True,
                    text=True,
                    cwd=self.app_path
                )
            else:
                # No previous tag, get all commits
                result = subprocess.run(
                    ["git", "log", "--pretty=format:%s"],
                    capture_output=True,
                    text=True,
                    cwd=self.app_path
                )
            
            if result.returncode != 0:
                # No previous tag, get all commits
                result = subprocess.run(
                    ["git", "log", "--pretty=format:%s"],
                    capture_output=True,
                    text=True,
                    cwd=self.app_path
                )
                
            commits = result.stdout.strip().split('\n') if result.stdout.strip() else []
            
            # Analyze commit messages
            major_bump = False
            minor_bump = False
            patch_bump = False
            
            for commit in commits:
                commit_lower = commit.lower()
                
                # Check for version bump indicators
                if any(indicator in commit_lower for indicator in ['breaking change', 'major:', '!:']):
                    major_bump = True
                elif any(indicator in commit_lower for indicator in ['feat:', 'feature:', 'add:']):
                    minor_bump = True
                elif any(indicator in commit_lower for indicator in ['fix:', 'bugfix:', 'patch:']):
                    patch_bump = True
                    
            # Determine version bump type
            if major_bump:
                return 'major'
            elif minor_bump:
                return 'minor'
            else:
                return 'patch'
                
        except Exception as e:
            print(f"Error analyzing commits: {e}")
            return 'patch'
            
    def get_commit_count_since_tag(self):
        """Get number of commits since last tag"""
        try:
            # First get the last tag safely
            tag_result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            
            if tag_result.returncode == 0:
                last_tag = tag_result.stdout.strip()
                result = subprocess.run(
                    ["git", "rev-list", "--count", "HEAD", f"^{last_tag}"],
                    capture_output=True,
                    text=True,
                    cwd=self.app_path
                )
            else:
                # No previous tag, count all commits
                result = subprocess.run(
                    ["git", "rev-list", "--count", "HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=self.app_path
                )
            
            if result.returncode == 0:
                return int(result.stdout.strip())
                
        except Exception:
            pass
            
        return 0
        
    def generate_version(self):
        """Generate next version based on commits"""
        major, minor, patch = self.get_current_version()
        bump_type = self.analyze_commits_since_tag()
        
        # Apply version bump
        if bump_type == 'major':
            major += 1
            minor = 0
            patch = 0
        elif bump_type == 'minor':
            minor += 1
            patch = 0
        else:  # patch
            patch += 1
            
        # Generate version string
        version = f"{major}.{minor}.{patch}"
        
        # Add pre-release info for non-main branches
        try:
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            
            branch = branch_result.stdout.strip()
            
            if branch and branch != 'main' and branch != 'master':
                # Add branch and commit info for pre-release
                commit_result = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=self.app_path
                )
                
                commit_hash = commit_result.stdout.strip()[:7]
                version = f"{version}-{branch}.{commit_hash}"
                
        except Exception:
            pass
            
        return version
        
    def update_version_file(self, version):
        """Update version in __init__.py"""
        init_file = self.app_path / "verenigingen" / "__init__.py"
        
        if init_file.exists():
            with open(init_file, 'r') as f:
                content = f.read()
                
            # Update version
            new_content = re.sub(
                r'__version__\s*=\s*["\'][^"\']*["\']',
                f'__version__ = "{version}"',
                content
            )
            
            if new_content != content:
                with open(init_file, 'w') as f:
                    f.write(new_content)
                    
    def generate_version_info(self, version):
        """Generate detailed version information"""
        info = {
            "version": version,
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "commit": "",
            "branch": "",
            "commits_since_tag": self.get_commit_count_since_tag(),
            "bump_type": self.analyze_commits_since_tag()
        }
        
        try:
            # Get current commit
            commit_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            info["commit"] = commit_result.stdout.strip()
            
            # Get branch
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            info["branch"] = branch_result.stdout.strip()
            
        except Exception:
            pass
            
        return info


def main():
    """Main entry point"""
    generator = VersionGenerator()
    version = generator.generate_version()
    
    # Update version file
    generator.update_version_file(version)
    
    # Output version (for GitHub Actions)
    print(version)
    
    # Also save detailed version info
    import json
    version_info = generator.generate_version_info(version)
    
    with open("version-info.json", "w") as f:
        json.dump(version_info, f, indent=2)


if __name__ == "__main__":
    main()