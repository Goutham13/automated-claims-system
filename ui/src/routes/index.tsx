import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { useAuth } from "@/context/AuthContext";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  const navigate = useNavigate();
  const { user } = useAuth();
  useEffect(() => {
    if (!user) { navigate({ to: "/login", replace: true }); return; }
    navigate({ to: user.role === "staff" ? "/staff/claims" : "/submit", replace: true });
  }, [user, navigate]);
  return null;
}
