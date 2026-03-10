import { useState, useEffect, useCallback } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import {
  Search,
  PenSquare,
  Sun,
  Moon,
  Monitor,
  LogOut,
  User,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { Avatar } from "@/components/ui/avatar";
import { useUIStore } from "@/stores/ui-store";
import { useAuth } from "@/hooks/use-auth";

function Header() {
  const { theme, setTheme, setComposeOpen } = useUIStore();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [searchValue, setSearchValue] = useState(
    searchParams.get("search") ?? ""
  );

  // Debounce search to URL params
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (searchValue) {
            next.set("search", searchValue);
          } else {
            next.delete("search");
          }
          return next;
        },
        { replace: true }
      );
    }, 300);

    return () => clearTimeout(timer);
  }, [searchValue, setSearchParams]);

  const handleLogout = useCallback(() => {
    void logout();
  }, [logout]);

  const cycleTheme = useCallback(() => {
    const order: Array<"light" | "dark" | "system"> = [
      "light",
      "dark",
      "system",
    ];
    const currentIndex = order.indexOf(theme);
    const nextIndex = (currentIndex + 1) % order.length;
    const nextTheme = order[nextIndex];
    if (nextTheme) setTheme(nextTheme);
  }, [theme, setTheme]);

  const ThemeIcon =
    theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;

  return (
    <header className="flex h-14 items-center gap-4 border-b bg-background px-4">
      {/* Search */}
      <div className="relative flex-1 max-w-md">
        <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          placeholder="Search emails..."
          className="pl-8"
          value={searchValue}
          onChange={(e) => setSearchValue(e.target.value)}
          data-search-input
        />
      </div>

      <div className="flex items-center gap-2 ml-auto">
        {/* Compose */}
        <Button
          size="sm"
          onClick={() => setComposeOpen(true)}
          className="gap-1.5"
        >
          <PenSquare className="h-4 w-4" />
          <span className="hidden sm:inline">Compose</span>
        </Button>

        {/* Theme toggle */}
        <Button variant="ghost" size="icon" onClick={cycleTheme} aria-label={`Switch theme (current: ${theme})`}>
          <ThemeIcon className="h-4 w-4" />
        </Button>

        {/* User menu */}
        <DropdownMenu>
          <DropdownMenuTrigger className="focus:outline-none">
            <Avatar
              name={user?.email ?? user?.username ?? "U"}
              size="sm"
            />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuLabel>
              <div className="flex flex-col space-y-1">
                <p className="text-sm font-medium">{user?.username}</p>
                <p className="text-xs text-muted-foreground">{user?.email}</p>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => navigate("/profile")}>
              <User className="mr-2 h-4 w-4" />
              Profile
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={handleLogout} destructive>
              <LogOut className="mr-2 h-4 w-4" />
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}

export { Header };
