# CSAI 302 — Advanced Database Systems

Student-facing course materials and reproducible lab infrastructure.

The course uses one PostgreSQL service and one database for the semester. Each lab owns a schema inside the course database, so students repeatedly use the same tools and data service without reinstalling PostgreSQL or creating a new database every week.

## Repository map

- docs/ contains the one-time setup and recurring workflow.
- infra/ contains the shared PostgreSQL Compose service.
- prelabs/ contains preparation guides and small conceptual examples.
- labs/ contains live-lab guides, starter files, and lab-specific database objects.
- project/ contains project guidance and milestone briefs as they are developed.

Optional practice challenges belong with the related live lab. Shared code or datasets should be added only when more than one lab genuinely reuses them.

## Start here

Follow docs/environment-setup.md once. For each lab, follow its guide and docs/recurring-workflow.md. Lab 1 is the first developed module; later lab folders are added as the course is built.

The database is persistent. Use a lab's reset instructions to reset only that lab's schema. Do not remove the PostgreSQL volume as part of routine lab work.

## Course project

Project briefs live here; each student team keeps its implementation in its own Git repository. Instructor solutions and grading notes belong in a separate private staff repository.
