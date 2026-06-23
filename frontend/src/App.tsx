import { PipelineProvider, usePipeline } from "./context/PipelineContext";
import { Nav } from "./components/Nav";
import { DealRoom } from "./pages/DealRoom";
import { PipelinePage } from "./pages/PipelinePage";
import { ReviewPage } from "./pages/ReviewPage";
import { ExportPage } from "./pages/ExportPage";

function Content() {
  const { page } = usePipeline();

  return (
    <>
      <Nav />
      {page === "deal-room" && <DealRoom />}
      {page === "pipeline" && <PipelinePage />}
      {page === "review" && <ReviewPage />}
      {page === "export" && <ExportPage />}
    </>
  );
}

export default function App() {
  return (
    <PipelineProvider>
      <div className="layout">
        <Content />
      </div>
    </PipelineProvider>
  );
}
