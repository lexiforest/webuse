import { ButtonLink } from "~/components/Button";
import ProjectForm, { booksToScrapeProject } from "~/components/ProjectForm";
import Layout from "~/layout/dashboard";

export default function CreateProject() {
  return (
    <Layout currentTab="projects">
      <div class="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-3xl font-bold text-sky-400">Create project</h1>
          <p class="mt-1 text-sm text-gray-400">Create a persisted scraping project</p>
        </div>
        <ButtonLink href="/projects">
          Back to projects
        </ButtonLink>
      </div>

      <ProjectForm
        endpoint="/api/projects"
        initialValue={booksToScrapeProject}
        method="POST"
        submitLabel="Create project"
      />
    </Layout>
  );
}
