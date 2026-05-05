import { Link, useNavigate } from "@tanstack/react-router";
import { ShieldCheck, Plus, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useClaims } from "@/context/ClaimsContext";
import { useAuth } from "@/context/AuthContext";

export function ClaimsHeader() {
  const navigate = useNavigate();
  const { resetDraft, clearActive } = useClaims();
  const { user, logout } = useAuth();

  const startNew = () => {
    resetDraft();
    clearActive();
    navigate({ to: "/submit" });
  };

  const handleLogout = () => {
    logout();
    navigate({ to: "/login", replace: true });
  };

  return (
    <header className="border-b border-border bg-background">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
        <Link to="/submit" className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <ShieldCheck className="h-4 w-4" />
          </span>
          <div className="leading-tight">
            <div className="text-sm font-semibold text-foreground">Claims Console</div>
            <div className="text-[11px] text-muted-foreground">Intake &amp; Review</div>
          </div>
        </Link>
        <div className="flex items-center gap-2">
          {user && (
            <span className="hidden text-xs text-muted-foreground sm:block">{user.name}</span>
          )}
          <Button size="sm" variant="outline" onClick={startNew} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            Start New Claim
          </Button>
          <Button size="sm" variant="ghost" onClick={handleLogout} className="gap-1.5">
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </Button>
        </div>
      </div>
    </header>
  );
}
