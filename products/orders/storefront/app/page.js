// Server components can call internal APIs listed under `calls` in product.yaml.
// Their URLs arrive as env vars, e.g. `calls: [backend]` -> process.env.BACKEND_URL
// (send a Google ID token for that audience; see Cloud Run service-to-service auth).
export default function Home() {
  return (
    <main>
      <h1>orders / storefront</h1>
    </main>
  );
}
