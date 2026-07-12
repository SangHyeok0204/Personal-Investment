import * as React from "react";
import { cn } from "@/lib/utils";

export function Table({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table
        className={cn("w-full border-collapse text-sm", className)}
        {...props}
      />
    </div>
  );
}

export function TableHead({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn(className)} {...props} />;
}

export function TableBody({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn(className)} {...props} />;
}

export function TableRow({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn("border-b border-hairline last:border-0", className)}
      {...props}
    />
  );
}

export function TableHeaderCell({
  className,
  ...props
}: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "bg-canvas-soft px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-ink-muted",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({
  className,
  ...props
}: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn("px-4 py-3 text-ink-secondary", className)}
      {...props}
    />
  );
}
