"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Upload, FileText } from "lucide-react";
import { ApiError, createTestJob, getJobs, uploadCsv } from "@/lib/api";
import { formatDateTime, shortId } from "@/lib/format";
import { PageContainer } from "@/components/layout/page-header";
import { Topbar } from "@/components/layout/topbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/status-badge";
import { ApiErrorBanner, EmptyState } from "@/components/states";
import { JobDetailDrawer } from "@/components/job-detail";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";

export default function DataOperationsPage() {
  const qc = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const jobs = useQuery({
    queryKey: ["jobs", { limit: 20 }],
    queryFn: () => getJobs({ limit: 20 }),
    refetchInterval: 3000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["jobStats"] });
  };

  const testJob = useMutation({
    mutationFn: () => createTestJob({ source: "web" }),
    onSuccess: invalidate,
  });

  const upload = useMutation({
    mutationFn: (f: File) => uploadCsv(f),
    onSuccess: () => {
      invalidate();
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
  });

  return (
    <>
      <Topbar
        title="데이터 작업"
        subtitle="Run background jobs and import portfolio CSV files."
        actions={
          <Button
            size="sm"
            onClick={() => testJob.mutate()}
            disabled={testJob.isPending}
          >
            <Play className="h-4 w-4" />
            {testJob.isPending ? "Starting…" : "Run test job"}
          </Button>
        }
      />
      <PageContainer>
        {jobs.isError && (
        <div className="mb-6">
          <ApiErrorBanner error={jobs.error} />
        </div>
      )}

      <Card className="mb-6">
        <CardHeader>
          <span className="eyebrow">Import</span>
          <CardTitle>CSV upload</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-ink-muted">
            Upload a portfolio CSV with columns{" "}
            <code className="rounded bg-canvas-soft px-1 py-0.5 font-mono text-xs text-ink-secondary">
              account_name, ticker, asset_name, quantity
            </code>
            . The file is validated and processed by the worker.
          </p>

          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block text-sm text-ink-muted file:mr-3 file:cursor-pointer file:rounded-md file:border file:border-hairline file:bg-canvas file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:bg-canvas-soft"
            />
            <Button
              variant="secondary"
              onClick={() => file && upload.mutate(file)}
              disabled={!file || upload.isPending}
            >
              <Upload className="h-4 w-4" />
              {upload.isPending ? "Uploading…" : "Upload"}
            </Button>
          </div>

          {upload.isSuccess && upload.data && (
            <div className="flex items-center gap-2 rounded-md border border-status-success/30 bg-status-success/[0.06] px-3 py-2 text-sm text-status-success">
              <FileText className="h-4 w-4 shrink-0" />
              <span>
                Import queued — job{" "}
                <span className="font-mono">{shortId(upload.data.job_id)}</span>{" "}
                created for {upload.data.original_filename}.
              </span>
            </div>
          )}
          {upload.isError && (
            <div className="rounded-md border border-status-failed/30 bg-status-failed/[0.06] px-3 py-2 text-sm text-status-failed">
              {upload.error instanceof ApiError
                ? upload.error.message
                : "Upload failed."}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <span className="eyebrow">Activity</span>
          <CardTitle>Jobs</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {jobs.isLoading ? (
            <div className="space-y-2 px-5 pb-5">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : jobs.isError ? (
            <div className="px-5 pb-5">
              <p className="text-sm text-ink-muted">
                Jobs are unavailable while the API is unreachable.
              </p>
            </div>
          ) : jobs.data && jobs.data.items.length > 0 ? (
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Type</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                  <TableHeaderCell>Created</TableHeaderCell>
                  <TableHeaderCell>Finished</TableHeaderCell>
                  <TableHeaderCell>ID</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {jobs.data.items.map((job) => (
                  <TableRow
                    key={job.id}
                    onClick={() => setSelectedJobId(job.id)}
                    className="cursor-pointer transition-colors hover:bg-canvas-soft"
                  >
                    <TableCell>
                      <Badge>{job.job_type}</Badge>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={job.status} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-ink-muted">
                      {formatDateTime(job.created_at)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-ink-muted">
                      {formatDateTime(job.finished_at)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-xs text-ink-faint">
                      {shortId(job.id)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="px-5 pb-5">
              <EmptyState message="No jobs yet. Run a test job to get started." />
            </div>
          )}
        </CardContent>
      </Card>

        {selectedJobId && (
          <JobDetailDrawer
            jobId={selectedJobId}
            onClose={() => setSelectedJobId(null)}
          />
        )}
      </PageContainer>
    </>
  );
}
