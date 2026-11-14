export const metadata = { title: "__PRODUCT__ / __NAME__" };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
