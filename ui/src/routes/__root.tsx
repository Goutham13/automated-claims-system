import { Outlet, createRootRoute, HeadContent, Scripts } from "@tanstack/react-router";

import appCss from "../styles.css?url";
import { ClaimsProvider } from "@/context/ClaimsContext";
import { AuthProvider, useAuth } from "@/context/AuthContext";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 text-xl font-semibold text-foreground">Page not found</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-6">
          <a
            href="/submit"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go to claim intake
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "Claims Console" },
      {
        name: "description",
        content:
          "Health insurance claims intake and review console with live processing trace.",
      },
      { name: "author", content: "Claims Console" },
      { property: "og:title", content: "Claims Console" },
      {
        property: "og:description",
        content:
          "Health insurance claims intake and review console with live processing trace.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
    links: [{ rel: "stylesheet", href: appCss }],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
});

function RootShell({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function ClaimsProviderScoped({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  return <ClaimsProvider key={user?.sub ?? "guest"}>{children}</ClaimsProvider>;
}

function RootComponent() {
  return (
    <AuthProvider>
      <ClaimsProviderScoped>
        <Outlet />
      </ClaimsProviderScoped>
    </AuthProvider>
  );
}
