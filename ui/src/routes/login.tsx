import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { loginUser } from "@/lib/auth-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2 } from "lucide-react";

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [{ title: "Sign In — Claims Portal" }],
  }),
  component: LoginPage,
});

function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [role, setRole] = useState<"member" | "staff">("member");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (user) {
      navigate({ to: user.role === "staff" ? "/staff/claims" : "/submit", replace: true });
    }
  }, [user, navigate]);

  const handleRoleSwitch = (r: "member" | "staff") => {
    setRole(r);
    setUsername("");
    setPassword("");
    setError(null);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError("Please enter your credentials.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await loginUser(username.trim(), password);
      login({ sub: res.sub, role: res.role, name: res.name, token: res.token });
      navigate({ to: res.role === "staff" ? "/staff/claims" : "/submit", replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-muted/30 px-4">
      <div className="mb-8 text-center">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Claims Portal</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Plum Health Insurance — Claim Intake & Review
        </p>
      </div>

      <div className="w-full max-w-sm">
        <div className="rounded-lg border border-border bg-card p-6 shadow-sm">
          {/* Role toggle */}
          <div className="mb-6 flex rounded-md border border-border p-1">
            {(["member", "staff"] as const).map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => handleRoleSwitch(r)}
                className={`flex-1 rounded py-1.5 text-sm font-medium transition-colors ${
                  role === r
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {r === "member" ? "Member" : "Staff"}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="username">
                {role === "member" ? "Member ID" : "Username"}
              </Label>
              <Input
                id="username"
                placeholder={role === "member" ? "e.g. EMP001" : "staff"}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>

            {error && (
              <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
                {error}
              </p>
            )}

            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Signing in…
                </>
              ) : (
                "Sign in"
              )}
            </Button>
          </form>

          {role === "member" && (
            <p className="mt-4 text-center text-xs text-muted-foreground">
              Use your Plum member ID (e.g. EMP001) and password{" "}
              <span className="font-mono">member123</span>
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
