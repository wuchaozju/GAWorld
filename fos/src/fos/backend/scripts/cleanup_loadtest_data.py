"""
Clean up all load test data from the database.

Removes k6 load test user accounts (loaduser1 through loaduserN)
and all their associated data. Also cleans up any orphaned
experiment records left behind by deleted simulations.

Usage:
  # See what would be deleted without making changes:
  python -m fos.backend.scripts.cleanup_loadtest_data --dry-run

  # Delete everything (with confirmation prompt):
  python -m fos.backend.scripts.cleanup_loadtest_data

  # Skip the confirmation prompt:
  python -m fos.backend.scripts.cleanup_loadtest_data --force

Environment variables (read from .env or FOS_DATABASE_URL):
  FOS_DATABASE_URL  - Database connection string (default: sqlite+aiosqlite:///./fos.db)
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select, text

from ..core.database import SessionLocal
from ..main import _prepare_database
from ..models.simulation import Simulation
from ..models.user import User


async def _count_all(session) -> dict:
    user_result = await session.execute(
        select(User).where(User.email.like("loaduser%@example.com"))
    )
    users = user_result.scalars().all()

    total_sims = 0
    total_nodes = 0
    total_logs = 0
    for user in users:
        sim_count = (
            await session.execute(
                select(Simulation).where(Simulation.owner_id == user.id)
            )
        ).scalars().all()
        total_sims += len(sim_count)
        for sim in sim_count:
            node_count = await session.execute(
                text("SELECT COUNT(*) FROM sim_tree_nodes WHERE simulation_id = :sid"),
                {"sid": sim.id},
            )
            total_nodes += node_count.scalar() or 0
            log_count = await session.execute(
                text("SELECT COUNT(*) FROM simulation_logs WHERE simulation_id = :sid"),
                {"sid": sim.id},
            )
            total_logs += log_count.scalar() or 0

    orphaned = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM experiments "
                "WHERE simulation_id NOT IN (SELECT id FROM simulations)"
            )
        )
    ).scalar() or 0

    return {
        "users": len(users),
        "simulations": total_sims,
        "tree_nodes": total_nodes,
        "logs": total_logs,
        "orphaned_experiments": orphaned,
    }


async def _delete_all(session, counts: dict, force: bool) -> None:
    if not force:
        print("\nThis will permanently delete:")
        print(f"  {counts['users']} load test user accounts")
        print(f"  {counts['simulations']} simulations")
        print(f"  {counts['tree_nodes']} tree nodes")
        print(f"  {counts['logs']} log entries")
        print(f"  {counts['orphaned_experiments']} orphaned experiments")
        print("\nAll related data (tokens, provider configs, etc.) will also be removed.")
        answer = input("\nProceed? [y/N] ").strip().lower()
        if answer != "y":
            print("Cancelled.")
            return

    # Delete orphaned experiments (no FK constraint, so they survive cascade)
    if counts["orphaned_experiments"] > 0:
        await session.execute(
            text(
                "DELETE FROM experiments "
                "WHERE simulation_id NOT IN (SELECT id FROM simulations)"
            )
        )
        print(f"  Deleted {counts['orphaned_experiments']} orphaned experiments")

    # Delete load test users (cascade handles sims, nodes, logs, tokens, etc.)
    if counts["users"] > 0:
        user_result = await session.execute(
            select(User).where(User.email.like("loaduser%@example.com"))
        )
        users = user_result.scalars().all()
        for user in users:
            await session.delete(user)
        await session.commit()
        print(f"  Deleted {counts['users']} load test users and all their data")
    else:
        print("  No load test users found to delete")

    print("Done.")


async def run(dry_run: bool = False, force: bool = False) -> None:
    await _prepare_database()
    async with SessionLocal() as session:
        counts = await _count_all(session)

        if dry_run or counts["users"] == 0:
            if counts["users"] == 0 and not dry_run:
                print("No load test users found.")
                return

            print(f"Load test user accounts:  {counts['users']}")
            print(f"Simulations owned by them: {counts['simulations']}")
            print(f"Tree nodes:               {counts['tree_nodes']}")
            print(f"Log entries:              {counts['logs']}")
            print(f"Orphaned experiments:     {counts['orphaned_experiments']}")

            if dry_run:
                print("\nThis was a dry run. No changes were made.")
                print('Re-run without --dry-run to actually delete.')
            return

        await _delete_all(session, counts, force)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean up k6 load test data from the database."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without making changes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()

    asyncio.run(run(dry_run=args.dry_run, force=args.force))


if __name__ == "__main__":
    main()
