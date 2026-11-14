import { createRoot } from "react-dom/client";

// A static SPA runs in the browser, so any API it calls directly must be
// public (`public: true` on that api component) or sit behind a load balancer.
createRoot(document.getElementById("root")).render(<h1>__PRODUCT__ / __NAME__</h1>);
